from dotenv import load_dotenv            # 從 python-dotenv 載入讀取 .env 檔案的函式
load_dotenv()                             # 讀取當前目錄或上層的 .env，將環境變數載入到 os.environ

import os                                  # 作業系統相關（路徑、環境變數、檔案操作）
import traceback                           # 取得完整例外堆疊字串，方便在開發時回傳詳細錯誤
from fastapi import FastAPI, File, UploadFile, HTTPException, Form  # FastAPI 主體與請求/例外/表單工具
from fastapi.middleware.cors import CORSMiddleware                  # CORS 中介層，讓前端（不同網域）可呼叫 API
from services import pdf_utils, vector_store, qna                   # 專案內部服務：PDF 解析、向量索引、問答邏輯
from routers.knowledge import router as knowledge_router            # 匯入自訂的 knowledge 路由（子路由）
from services import text_extractor
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# 初始化向量庫（會自動載入已有的 index 和 metadata）
# vector_store.init_index(1536)  # OpenAI ada-002 向量長度 dotenv

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

# 處理網址
def _extract_text_from_url(url: str, timeout: int = 12) -> str:
    """下載 HTML，移除 script/style，回傳乾淨文字。"""
    # 基本網址驗證（避免奇怪 scheme）
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="只支援 http/https 網址")

    try:
        # 下載
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Medical-QA/1.0)"
        })
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"連線失敗：{e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"無法讀取網址（HTTP {resp.status_code}）")

    # 若是 PDF/檔案，建議你導回 /upload 流程
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype or "octet-stream" in ctype:
        raise HTTPException(status_code=415, detail="偵測到非 HTML 檔案，請改用 /upload 上傳檔案。")

    # 粗略大小限制（避免超大頁面）
    if len(resp.content) > 2 * 1024 * 1024:  # 2MB
        raise HTTPException(status_code=413, detail="頁面過大（>2MB），請改上傳檔案或提供摘要。")

    # 解析 HTML → 純文字
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    text = soup.get_text(separator="\n", strip=True)

    # 簡單清理
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join([ln for ln in lines if ln])

    if len(text) < 100:
        raise HTTPException(status_code=400, detail="頁面文字過少或非文章頁，無法分析。")

    return text



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

# app.py（只貼出需要修改/新增的重點）
from pathlib import Path
from services import pdf_utils, vector_store, qna
from services import text_extractor  # ★ 新增

from fastapi import Request, Query
from typing import List, Optional


@app.post("/fetch_url", summary="讀取網址內容並進行問答（不持久保存）")
async def fetch_url(
    url: str = Form(...),
    query: str = Form("請用上面網址內容條列重點並進行摘要"),
    top_k: int = Form(5),
    mode: str = Form("auto"),
):
    """
    讀取指定 URL → 擷取文字 → 臨時建立向量集合 → 問答 → 立即清空集合。
    不會長期保存內容。
    """
    try:
        # 1) 取文
        fulltext = _extract_text_from_url(url)

        # === 切段與清理 ===
        def approx_tokens(s: str) -> int:
            return max(1, int(len(s) / 3.5))  # 粗估 tokens 數

        def chunk_text(text: str, max_tokens_per_chunk: int = 400):
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            chunks, cur, cur_tok = [], [], 0
            for ln in lines:
                t = approx_tokens(ln)
                if cur_tok + t > max_tokens_per_chunk and cur:
                    chunks.append("\n".join(cur))
                    cur, cur_tok = [], 0
                cur.append(ln)
                cur_tok += t
            if cur:
                chunks.append("\n".join(cur))
            return chunks

        import re
        def light_clean(s: str) -> str:
            s = re.sub(r'\n{2,}', '\n', s)
            s = re.sub(r'(cookie|accept|privacy).{0,40}', '', s, flags=re.I)
            s = re.sub(r'(terms|subscribe|sign in|login).{0,40}', '', s, flags=re.I)
            return s

        cleaned = light_clean(fulltext)
        segments = chunk_text(cleaned, max_tokens_per_chunk=400)

        # === 取得全部分段 ===
        selected = segments

        # 加一個「極限上限」避免惡意超長頁耗死記憶體，例如 50k tokens：
        HARD_MAX_TOKENS = 50000
        total_toks = sum(max(1, int(len(s)/3.5)) for s in selected)
        if total_toks > HARD_MAX_TOKENS:
            # 保守只取前面到 50k tokens 為止
            kept, acc = [], 0
            for s in selected:
                t = max(1, int(len(s)/3.5))
                if acc + t > HARD_MAX_TOKENS:
                    break
                kept.append(s)
                acc += t
            selected = kept

        paragraphs = [{"page": 1, "text": s, "source": url} for s in selected]

        # === 向量化 ===
        vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
        if not vectors:
            raise HTTPException(status_code=500, detail="向量產生失敗")
        dim = len(vectors[0])

        # === 臨時 collection ===
        import hashlib
        cid = "_url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        vector_store.reset_collection(cid, dim)

        for p in paragraphs:
            p.setdefault("source", url)
        vector_store.add_embeddings(cid, vectors, paragraphs)

        # === 問答 ===
        answer, mode_used, meta = qna.answer_question(
            query=query,
            top_k=top_k,
            mode=mode,
            sources=None,
            collection_id=cid,
        )

        # === 清空臨時集合 ===
        try:
            vector_store.reset_collection(cid, dim)
        except Exception:
            pass

        # === 回傳結果 ===
        return {
            "ok": True,
            "url": url,
            "question": query,
            "answer": answer,
            "mode": mode_used,
            "usage": meta.get("usage", {}),
            "sources": meta.get("sources", []),
            "cost_usd": round(meta.get("total_cost_usd", 0.0), 6),
            "embedding_cost": round(meta.get("embedding_cost", 0.0), 6),
            "chat_cost": round(meta.get("chat_cost", 0.0), 6),
            "transcribe_cost": round(meta.get("transcribe_cost", 0.0), 6),
        }

    except HTTPException:
        raise
    except Exception:
        import traceback
        detail = traceback.format_exc()
        raise HTTPException(status_code=500, detail=detail)




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
