from dotenv import load_dotenv            # 從 python-dotenv 載入讀取 .env 檔案的函式
load_dotenv()                             # 讀取當前目錄或上層的 .env，將環境變數載入到 os.environ

import os                                  # 作業系統相關（路徑、環境變數、檔案操作）
import traceback                           # 取得完整例外堆疊字串，方便在開發時回傳詳細錯誤
from fastapi import FastAPI, File, UploadFile, HTTPException, Form  # FastAPI 主體與請求/例外/表單工具
from fastapi.middleware.cors import CORSMiddleware                  # CORS 中介層，讓前端（不同網域）可呼叫 API
from services import pdf_utils, vector_store, qna                   # 專案內部服務：PDF 解析、向量索引、問答邏輯
from routers.knowledge import router as knowledge_router            # 匯入自訂的 knowledge 路由（子路由）
from services import text_extractor

# 初始化向量庫（會自動載入已有的 index 和 metadata）
# vector_store.init_index(1536)  # OpenAI ada-002 向量長度

# .\.venv\Scripts\Activate.ps1              # （備忘）啟動虛擬環境的 PowerShell 指令
# python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000   # （備忘）啟動開發伺服器
# http://127.0.0.1:8000/docs               # （備忘）Swagger UI 文件入口 不聽聲音的話，可以知道這影片在教導甚麼嗎
#  deactivate 


app = FastAPI(                             # 建立 FastAPI 應用實例
    title="Medical QA Backend",            # API 標題（顯示於 /docs 頁面）
    description="上傳醫學PDF並進行問答的後端服務",  # API 描述（顯示於 /docs 頁面）
    version="0.1.0"                        # 版本號
)

ALLOWED_EXTS = {".txt", ".html", ".htm", ".pdf", ".docx", ".pptx",".mp3", ".wav", ".m4a",".mp4", ".mov", ".m4v"}#可讀取的文件

# 單位：MB
LIMITS_MB = {
    # 文檔（純文字）
    "txt": 5, "html": 5, "htm": 5,
    # PDF/Office
    "pdf": 25, "docx": 25, "pptx": 25,
    # 音訊
    "mp3": 50, "wav": 50, "m4a": 50,
    # 影片
    "mp4": 100, "mov": 100, "m4v": 100,
}

app.include_router(knowledge_router)       # 掛載外部子路由（/knowledge 等），讓該 router 內的端點生效
app.add_middleware(                        # 加入 CORS 中介層，允許跨網域請求
    CORSMiddleware,
    allow_origins=["*"],                   # 允許的來源（* 表示全部；正式環境建議改成白名單）
    allow_methods=["*"],                   # 允許的 HTTP 方法（GET/POST/…）
    allow_headers=["*"],                   # 允許的自訂標頭
)

# === cost tracking: imports & config ===
import os, json, subprocess
from pathlib import Path

PRICE_WHISPER_PER_MIN = float(os.getenv("PRICE_WHISPER_PER_MIN", "0.006"))

COST_STORE = Path("data") / "costs.json"
COST_STORE.parent.mkdir(parents=True, exist_ok=True)

def _load_costs():
    if COST_STORE.exists():
        try:
            return json.loads(COST_STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_costs(d):
    COST_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def add_pending_transcribe_cost(collection_id: str, amount: float):
    d = _load_costs()
    node = d.setdefault(collection_id or "_default", {})
    cur = float(node.get("pending_transcribe_cost", 0.0))
    node["pending_transcribe_cost"] = round(cur + float(amount), 6)
    _save_costs(d)

def get_media_duration_sec(path: str) -> float:
    """用 ffprobe 取得影音長度（秒）"""
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    )
    info = json.loads(out)
    try:
        return float(info.get("format", {}).get("duration", 0.0)) or 0.0
    except Exception:
        return 0.0
# === end cost tracking ===


"""
@app.post("/upload", summary="上傳醫學PDF文件")  # 定義 POST /upload 端點，摘要顯示於 /docs
async def upload_pdf(file: UploadFile = File(...)):  # 參數 file：表單檔案欄位（必填）；UploadFile 可流式讀取
    try:                                # 例外處理區塊開始
        if file.content_type not in ("application/pdf", "application/octet-stream"):  # 檢查 MIME 類型
            raise HTTPException(status_code=400, detail="請上傳 PDF 檔案")  # 非 PDF 則回 400 Bad Request

        upload_dir = "data/uploads"         # 設定檔案儲存資料夾（相對路徑）
        os.makedirs(upload_dir, exist_ok=True)  # 若不存在則建立資料夾（多層可同時建立）
        file_path = os.path.join(upload_dir, file.filename)  # 目標儲存的完整路徑

        contents = await file.read()        # 非同步一次性讀取上傳內容（小檔案可；大檔建議分段）
        with open(file_path, "wb") as f:    # 以二進位寫入模式打開目標檔案
            f.write(contents)               # 將上傳內容寫入磁碟
        await file.close()                  # 關閉上傳檔案的資源（UploadFile）

        pages_text = pdf_utils.extract_text_by_page(file_path)  # 呼叫服務：逐頁擷取 PDF 文字，回傳 list[str]
        paragraphs = pdf_utils.split_into_paragraphs(pages_text)  # 呼叫服務：按規則分段（回傳含 page/text 的列表）
        if not paragraphs:                  # 若分段結果為空，視為解析失敗
            raise HTTPException(status_code=500, detail="PDF 內容為空或解析失敗")  # 回 500，提示前端

        vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])  # 將每個段落送 Embedding 取得向量
        vector_store.add_embeddings(vectors, paragraphs)  # 將向量與段落一起加入向量索引（FAISS 等）

        return {                             # 成功回應：回傳檔名與索引段落數
            "message": f"已上傳並索引：{file.filename}",
            "paragraphs_indexed": len(paragraphs)
        }

    except HTTPException:                    # 若是我們主動丟出的 HTTPException，原封不動往外拋
        raise
    except Exception:                        # 其他未預期錯誤
        # 開發期：把完整堆疊回傳，方便你在 Swagger 直接看到哪一行壞了
        detail = traceback.format_exc()      # 將完整例外堆疊轉成字串
        raise HTTPException(status_code=500, detail=detail)  # 回 500 並附上堆疊（正式環境可改為隱藏）
"""
# app.py（只貼出需要修改/新增的重點）
from pathlib import Path
from services import pdf_utils, vector_store, qna
from services import text_extractor  # ★ 新增

from fastapi import Request, Query
from typing import List, Optional

@app.post("/upload", summary="上傳文件")
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    collectionId: str = Form(None),
    mode: str = Form("overwrite"),
):
    try:
        # === 1) 驗證副檔名與上限 ===
        ext_with_dot = Path(file.filename).suffix.lower()
        if ext_with_dot not in ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"不支援的檔案格式：{ext_with_dot}，可用：{', '.join(sorted(ALLOWED_EXTS))}"
            )
        ext = ext_with_dot.lstrip(".")
        limit_mb = LIMITS_MB[ext]
        limit_bytes = limit_mb * 1024 * 1024

        # === 2) Content-Length 粗檢 ===
        cl = request.headers.get("content-length")
        if cl and int(cl) > int(limit_bytes * 1.2):
            raise HTTPException(status_code=413, detail=f"檔案過大（上限 {limit_mb}MB）")

        # === 3) 實際讀入檔案內容 ===
        contents = await file.read()
        if len(contents) > limit_bytes:
            raise HTTPException(status_code=413, detail=f"檔案過大（上限 {limit_mb}MB）")

        # === 4) 儲存檔案 ===
        upload_dir = "data/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(file.filename)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(contents)
        await file.close()

        # # === 5) 文字/影音抽取（統一 extract_any） ===
        # fulltext, vision_cost = text_extractor.extract_any(file_path)

        # # === 6) 切段 ===
        # paragraphs = pdf_utils.split_into_paragraphs(fulltext)
        # if not paragraphs:
        #     raise HTTPException(status_code=500, detail="文件內容為空或解析失敗")

                # === 5) 文字/影音抽取（統一 extract_any） ===
        fulltext, vision_cost = text_extractor.extract_any(file_path)

        # === 6) 切段（改為包裝成頁面形式） ===
        if not fulltext.strip():
            raise HTTPException(status_code=500, detail="文件內容為空或解析失敗")

        pages_text = [(1, fulltext)]   # ← 把整篇包成單頁
        paragraphs = pdf_utils.split_into_paragraphs(pages_text)
        if not paragraphs:
            raise HTTPException(status_code=500, detail="切段失敗（可能內容過短或格式錯誤）")


        # === 7) 向量化 ===
        vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
        if not vectors:
            raise HTTPException(status_code=500, detail="向量產生失敗")
        dim = len(vectors[0])

        # === 8) collectionId 驗證與索引重建 ===
        def _norm_collection_id(cid: str | None) -> str:
            cid = (cid or "_default").strip()
            import re
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
                raise HTTPException(status_code=400, detail="非法的 collectionId")
            return cid

        cid = _norm_collection_id(collectionId)

        # 模式選擇
        if mode == "overwrite":
            vector_store.reset_collection(cid, dim)
        else:
            vector_store.init_collection(cid, dim)

        # === 9) 加入來源與儲存 ===
        src = file.filename
        for p in paragraphs:
            p.setdefault("source", src)
        vector_store.add_embeddings(cid, vectors, paragraphs)

        # === 10) 影音轉錄費（Whisper 成本暫存） ===
        is_audio = ext in {"mp3", "wav", "m4a"}
        is_video = ext in {"mp4", "mov", "m4v"}

        transcribe_cost = 0.0
        if is_audio or is_video:
            dur_sec = get_media_duration_sec(str(file_path))
            minutes = dur_sec / 60.0
            transcribe_cost = round(minutes * PRICE_WHISPER_PER_MIN, 6)
            add_pending_transcribe_cost(cid, transcribe_cost)

        # === 11) 成本統計 ===
        embedding_cost = round(len(paragraphs) * 0.00001, 6)
        total_cost = round(transcribe_cost + vision_cost + embedding_cost, 6)

        # === 12) 回傳結果 ===
        return {
            "ok": True,
            "message": f"已上傳並索引：{safe_name}",
            "collectionId": cid,
            "mode": mode,
            "filetype": ext_with_dot,
            "limit_mb": limit_mb,
            "size_mb": round(len(contents) / (1024 * 1024), 2),
            "paragraphs_indexed": len(paragraphs),
            "transcribe_cost": transcribe_cost,
            "vision_cost": vision_cost,
            "embedding_cost": embedding_cost,
            "total_cost_usd": total_cost,
        }

    except HTTPException:
        raise
    except Exception:
        import traceback
        detail = traceback.format_exc()
        raise HTTPException(status_code=500, detail=detail)





        
@app.post("/ask", summary="醫學問答查詢")
async def ask_question(
    query: str = Form(...),
    top_k: int = Form(5),
    mode: str = Form("auto"),
    source: Optional[List[str]] = Query(None),
    collectionId: str = Form(None),   # ★ 新增：指定要查詢的 collection
):
    """
    回傳問答結果 + 成本細項：
      - cost_usd: 總花費
      - embedding_cost: 上傳嵌入費用
      - chat_cost: 問答生成費用
      - transcribe_cost: 影音轉錄費
    """
    try:
        # === 驗證 / 正規化 collectionId ===
        def _norm_collection_id(cid: str | None) -> str:
            cid = (cid or "_default").strip()
            import re
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
                raise HTTPException(status_code=400, detail="非法的 collectionId")
            return cid

        cid = _norm_collection_id(collectionId)

        # === 呼叫 QnA 模組（傳入 collectionId） ===
        answer, mode_used, meta = qna.answer_question(
            query=query,
            top_k=top_k,
            mode=mode,
            sources=source,
            collection_id=cid,   # ★ 傳進 qna.py
        )

        # === 整理回傳 ===
        return {
            "ok": True,
            "collectionId": cid,  # ★ 回傳目前查詢的 collection
            "question": query,
            "answer": answer,
            "mode": mode_used,
            "cost_usd": round(meta.get("total_cost_usd", 0.0), 6),
            "embedding_cost": round(meta.get("embedding_cost", 0.0), 6),
            "chat_cost": round(meta.get("chat_cost", 0.0), 6),
            "transcribe_cost": round(meta.get("transcribe_cost", 0.0), 6),
            "usage": meta.get("usage", {}),
            "sources": meta.get("sources", []),
        }

    except HTTPException:
        raise
    except Exception:
        import traceback
        detail = traceback.format_exc()
        raise HTTPException(status_code=500, detail=detail)




    # .\.venv\Scripts\Activate.ps1           # （備忘）再次提醒啟動虛擬環境
    # python -m uvicorn app:app              # （備忘）再次提醒啟動伺服器指令
