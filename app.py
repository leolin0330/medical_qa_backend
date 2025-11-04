from dotenv import load_dotenv            # 從 python-dotenv 載入讀取 .env 檔案的函式
load_dotenv()                             # 讀取當前目錄或上層的 .env，將環境變數載入到 os.environ

import os                                  # 作業系統相關（路徑、環境變數、檔案操作）
import traceback                           # 取得完整例外堆疊字串，方便在開發時回傳詳細錯誤
from fastapi import FastAPI, File, UploadFile, HTTPException, Form  # FastAPI 主體與請求/例外/表單工具
from fastapi.middleware.cors import CORSMiddleware                  # CORS 中介層，讓前端（不同網域）可呼叫 API
from services import text_extractor  # ★ 新增
from services import pdf_utils, vector_store, qna                   # 專案內部服務：PDF 解析、向量索引、問答邏輯
from routers.knowledge import router as knowledge_router            # 匯入自訂的 knowledge 路由（子路由）
from services import text_extractor
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
from pathlib import Path
from fastapi import Request, Query
from typing import List, Optional




# 初始化向量庫（會自動載入已有的 index 和 metadata）
# vector_store.init_index(1536)  # OpenAI ada-002 向量長度 dotenv

# .\.venv\Scripts\Activate.ps1              # （備忘）啟動虛擬環境的 PowerShell 指令
# python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000   # （備忘）啟動開發伺服器
# http://127.0.0.1:8000/docs               # （備忘）Swagger UI 文件入口 
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

# 偵測網址
URL_RE = re.compile(r"https?://[^\s]+")


def _norm_collection_id(cid: Optional[str]) -> Optional[str]:
    INVALID_VALUES = {"", "string", "null", "undefined", "none"}
    if cid is None or cid.strip().lower() in INVALID_VALUES:
        return None
    cid = cid.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
        raise HTTPException(status_code=400, detail="非法的 collectionId")
    return cid

def _split_url_and_instruction(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    從 text 中抓第一個 URL；其餘文字視為 instruction。
    回傳: (url 或 None, instruction 或 None)
    """
    m = URL_RE.search(text)
    if not m:
        return None, text.strip() or None
    url = m.group(0)
    # 去掉第一個 url 後的殘餘字串
    inst = (text[:m.start()] + text[m.end():]).strip()
    return url, (inst if inst else None)


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
    # if "pdf" in ctype or "octet-stream" in ctype:
    #     raise HTTPException(status_code=415, detail="偵測到非 HTML 檔案，請改用 /upload 上傳檔案。")
    # 只允許純文字型內容，其餘都拒絕
    if not any(t in ctype for t in ["text/html", "text/plain", "application/xhtml"]):
        raise HTTPException(
            status_code=415,
            detail=f"目前僅支援一般網頁文字，偵測到 Content-Type={ctype}，請改用 /upload 上傳檔案。"
        )

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

# 清理工具（避免 Swagger 預設 "string" 亂入）
def _clean_str(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    v = val.strip()
    if not v or v.lower() in {"string", "null", "none", "undefined"}:
        return None
    return v


async def _answer_from_url(url: str, top_k: int = 5, summary_query: str | None = None):
    """
    讀取 URL → 取正文 → 切段 → 向量化 → 建立臨時 collection → 用 doc 模式回答 → 清理臨時 collection
    回傳格式與 /ask、/fetch_url 對齊。
    """
    # 1) 取文（沿用你現有的 _extract_text_from_url）
    fulltext = _extract_text_from_url(url)

    # 2) 清理 + 切段（沿用你在 fetch_url 的做法）
    def approx_tokens(s: str) -> int:
        return max(1, int(len(s) / 3.5))

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

    import re as _re
    def light_clean(s: str) -> str:
        s = _re.sub(r'\n{2,}', '\n', s)
        s = _re.sub(r'(cookie|accept|privacy).{0,40}', '', s, flags=_re.I)
        s = _re.sub(r'(terms|subscribe|sign in|login).{0,40}', '', s, flags=_re.I)
        return s

    cleaned = light_clean(fulltext)
    segments = chunk_text(cleaned, max_tokens_per_chunk=400)

    # 上限保護（最多 ~50k tokens）
    HARD_MAX_TOKENS = 50000
    kept, acc = [], 0
    for s in segments:
        t = approx_tokens(s)
        if acc + t > HARD_MAX_TOKENS:
            break
        kept.append(s); acc += t

    paragraphs = [{"page": 1, "text": s, "source": url} for s in kept]

    # 3) 向量化
    vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
    if not vectors:
        raise HTTPException(status_code=500, detail="向量產生失敗")
    dim = len(vectors[0])

    # 4) 臨時 collection
    import hashlib
    cid = "_url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    vector_store.reset_collection(cid, dim)
    vector_store.add_embeddings(cid, vectors, paragraphs)

    # 5) 問答（doc 模式）
    user_query = summary_query or "請用上面網址內容條列重點並進行摘要"
    answer, mode_used, meta = qna.answer_question(
        query=user_query, top_k=top_k, mode="doc", sources=None, collection_id=cid
    )

    # 6) 清空臨時 collection（避免累積）
    try:
        vector_store.reset_collection(cid, dim)
    except Exception:
        pass

    # 7) 回傳
    return {
        "ok": True,
        "url": url,
        "question": user_query,
        "answer": answer,
        "mode": mode_used,  # "doc"
        "usage": meta.get("usage", {}),
        "sources": meta.get("sources", []),
        "cost_usd": round(meta.get("total_cost_usd", 0.0), 6),
        "embedding_cost": round(meta.get("embedding_cost", 0.0), 6),
        "chat_cost": round(meta.get("chat_cost", 0.0), 6),
        "transcribe_cost": round(meta.get("transcribe_cost", 0.0), 6),
        "collectionId": cid,
    }


@app.post("/fetch_url", summary="讀取網址內容並進行問答（不持久保存）")
async def fetch_url(
    url: str = Form(...),
    query: str = Form("請用上面網址內容條列重點並進行摘要"),
    top_k: int = Form(5),
):
    try:
        return await _answer_from_url(url, top_k=top_k, summary_query=query)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())



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
            INVALID_VALUES = {"", "string", "null", "undefined", "none"}
            if cid is None or cid.strip().lower() in INVALID_VALUES:
                return "_default"
            cid = cid.strip()
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





        
@app.post("/ask", summary="醫學問答查詢（支援純文字 / 純網址 / 網址+指令）")
async def ask_question(
    query: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    instruction: Optional[str] = Form(None),
    top_k: int = Form(5),
    source: Optional[List[str]] = Query(None),
    collectionId: Optional[str] = Form(None),
):
    """
    支援：
    1) 純文字：query="請解釋xxx"
    2) 純網址：url="https://pmc...."
    3) 網址+指令：
       - 方式A：query="https://pmc.... 整理重點"
       - 方式B：url="https://pmc...."  +  instruction="整理重點"
    """
    try:
        # --- 清理 Swagger 預設值 ---
        def _clean_str(val: Optional[str]) -> Optional[str]:
            if val is None:
                return None
            v = val.strip()
            if not v or v.lower() in {"string", "null", "none", "undefined"}:
                return None
            return v

        query = _clean_str(query)
        url = _clean_str(url)
        instruction = _clean_str(instruction)
        collectionId = _clean_str(collectionId)

        cid = _norm_collection_id(collectionId)
        sources = [s for s in (source or []) if s] or None
        pure_text: Optional[str] = None

        # --- 先拆網址與文字 ---
        if url:
            url = url.strip()
            # 若不是合法網址，視為純文字問題
            if not URL_RE.match(url):
                merged = " ".join(x for x in [(query or ""), url, (instruction or "")] if x).strip()
                pure_text = merged or None
                url = None
                instruction = None
        elif query:
            q = query.strip()
            u, inst = _split_url_and_instruction(q)
            if u:
                url = u
                instruction = instruction or inst
            else:
                pure_text = q
        else:
            raise HTTPException(status_code=400, detail="缺少 query 或 url")

        # --- 分支處理 ---
        if url:
            # ✅ 真的抓網址內容並回答
            return await _answer_from_url(
                url,
                top_k=top_k,
                summary_query=instruction or "請用上面網址內容條列重點並進行摘要",
            )

        # ✅ 純文字情境
        answer, mode_used, meta = qna.answer_question(
            query=pure_text,
            top_k=top_k,
            mode="doc" if (sources or cid) else "general",
            sources=sources,
            collection_id=cid,
        )

        return {
            "ok": True,
            "collectionId": cid or meta.get("collection_id"),
            "question": pure_text,
            "answer": answer,
            "mode": mode_used,
            "cost_usd": round(meta.get("total_cost_usd", 0.0), 6),
            "embedding_cost": round(meta.get("embedding_cost", 0.0), 6),
            "chat_cost": round(meta.get("chat_cost", 0.0), 6),
            "transcribe_cost": round(meta.get("transcribe_cost", 0.0), 6),
            "usage": meta.get("usage", {}),
            "sources": meta.get("sources", []) or (sources or []),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



    # .\.venv\Scripts\Activate.ps1           # （備忘）再次提醒啟動虛擬環境
    # python -m uvicorn app:app              # （備忘）再次提醒啟動伺服器指令
