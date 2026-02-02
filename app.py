# from dotenv import load_dotenv            # 從 python-dotenv 載入讀取 .env 檔案的函式
# load_dotenv()                             # 讀取當前目錄或上層的 .env，將環境變數載入到 os.environ

# import os                                  # 作業系統相關（路徑、環境變數、檔案操作）
# import traceback                           # 取得完整例外堆疊字串，方便在開發時回傳詳細錯誤
# from fastapi import FastAPI, File, UploadFile, HTTPException, Form  # FastAPI 主體與請求/例外/表單工具
# from fastapi.middleware.cors import CORSMiddleware                  # CORS 中介層，讓前端（不同網域）可呼叫 API
# from services import text_extractor  # ★ 新增
# from services import pdf_utils, vector_store, qna                   # 專案內部服務：PDF 解析、向量索引、問答邏輯
# from routers.knowledge import router as knowledge_router            # 匯入自訂的 knowledge 路由（子路由）
# from services import text_extractor
# import requests
# from bs4 import BeautifulSoup
# from urllib.parse import urlparse
# import re
# from pathlib import Path
# from fastapi import Request, Query
# from typing import List, Optional




# # 初始化向量庫（會自動載入已有的 index 和 metadata）
# # vector_store.init_index(1536)  # OpenAI ada-002 向量長度 dotenv

# # .\.venv\Scripts\Activate.ps1              # （備忘）啟動虛擬環境的 PowerShell 指令
# # python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000   # （備忘）啟動開發伺服器
# # http://127.0.0.1:8000/docs               # （備忘）Swagger UI 文件入口 
# #  deactivate 


# app = FastAPI(                             # 建立 FastAPI 應用實例
#     title="Medical QA Backend",            # API 標題（顯示於 /docs 頁面）
#     description="上傳醫學PDF並進行問答的後端服務",  # API 描述（顯示於 /docs 頁面）
#     version="0.1.0"                        # 版本號
# )

# ALLOWED_EXTS = {".txt", ".html", ".htm", ".pdf", ".docx", ".pptx",
#                 ".mp3", ".wav", ".m4a",".mp4", ".mov", ".m4v",
#                 ".jpg", ".jpeg", ".png", ".bmp", 
#                 }#可讀取的文件

# # 單位：MB
# LIMITS_MB = {
#     # 文檔（純文字）
#     "txt": 5, "html": 5, "htm": 5,
#     # PDF/Office
#     "pdf": 25, "docx": 25, "pptx": 25,
#     # 音訊
#     "mp3": 50, "wav": 50, "m4a": 50,
#     # 影片
#     "mp4": 100, "mov": 100, "m4v": 100,
#     # 圖片
#      "jpg": 10, "jpeg": 10, "png": 10, "bmp": 10,
# }

# app.include_router(knowledge_router)       # 掛載外部子路由（/knowledge 等），讓該 router 內的端點生效
# app.add_middleware(                        # 加入 CORS 中介層，允許跨網域請求
#     CORSMiddleware,
#     allow_origins=["*"],                   # 允許的來源（* 表示全部；正式環境建議改成白名單）
#     allow_methods=["*"],                   # 允許的 HTTP 方法（GET/POST/…）
#     allow_headers=["*"],                   # 允許的自訂標頭
# )

# # 偵測網址
# URL_RE = re.compile(r"https?://[^\s]+")


# def _norm_collection_id(cid: Optional[str]) -> Optional[str]:
#     INVALID_VALUES = {"", "string", "null", "undefined", "none"}
#     if cid is None or cid.strip().lower() in INVALID_VALUES:
#         return None
#     cid = cid.strip()
#     if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
#         raise HTTPException(status_code=400, detail="非法的 collectionId")
#     return cid

# def _split_url_and_instruction(text: str) -> tuple[Optional[str], Optional[str]]:
#     """
#     從 text 中抓第一個 URL；其餘文字視為 instruction。
#     回傳: (url 或 None, instruction 或 None)
#     """
#     m = URL_RE.search(text)
#     if not m:
#         return None, text.strip() or None
#     url = m.group(0)
#     # 去掉第一個 url 後的殘餘字串
#     inst = (text[:m.start()] + text[m.end():]).strip()
#     return url, (inst if inst else None)


# # 處理網址
# def _extract_text_from_url(url: str, timeout: int = 12) -> str:
#     """下載 HTML，移除 script/style，回傳乾淨文字。"""
#     # 基本網址驗證（避免奇怪 scheme）
#     parsed = urlparse(url)
#     if parsed.scheme not in {"http", "https"}:
#         raise HTTPException(status_code=400, detail="只支援 http/https 網址")

#     try:
#         # 下載
#         resp = requests.get(url, timeout=timeout, headers={
#             "User-Agent": "Mozilla/5.0 (Medical-QA/1.0)"
#         })
#     except requests.RequestException as e:
#         raise HTTPException(status_code=400, detail=f"連線失敗：{e}")

#     if resp.status_code != 200:
#         raise HTTPException(status_code=400, detail=f"無法讀取網址（HTTP {resp.status_code}）")

#     # 若是 PDF/檔案，建議你導回 /upload 流程
#     ctype = (resp.headers.get("Content-Type") or "").lower()
#     # if "pdf" in ctype or "octet-stream" in ctype:
#     #     raise HTTPException(status_code=415, detail="偵測到非 HTML 檔案，請改用 /upload 上傳檔案。")
#     # 只允許純文字型內容，其餘都拒絕
#     if not any(t in ctype for t in ["text/html", "text/plain", "application/xhtml"]):
#         raise HTTPException(
#             status_code=415,
#             detail=f"目前僅支援一般網頁文字，偵測到 Content-Type={ctype}，請改用 /upload 上傳檔案。"
#         )

#     # 粗略大小限制（避免超大頁面）
#     if len(resp.content) > 2 * 1024 * 1024:  # 2MB
#         raise HTTPException(status_code=413, detail="頁面過大（>2MB），請改上傳檔案或提供摘要。")

#     # 解析 HTML → 純文字
#     soup = BeautifulSoup(resp.text, "html.parser")
#     for tag in soup(["script", "style", "noscript"]):
#         tag.extract()
#     text = soup.get_text(separator="\n", strip=True)

#     # 簡單清理
#     lines = [ln.strip() for ln in text.splitlines()]
#     text = "\n".join([ln for ln in lines if ln])

#     if len(text) < 100:
#         raise HTTPException(status_code=400, detail="頁面文字過少或非文章頁，無法分析。")

#     return text



# # === cost tracking: imports & config ===
# import os, json, subprocess
# from pathlib import Path

# PRICE_WHISPER_PER_MIN = float(os.getenv("PRICE_WHISPER_PER_MIN", "0.006"))

# COST_STORE = Path("data") / "costs.json"
# COST_STORE.parent.mkdir(parents=True, exist_ok=True)

# def _load_costs():
#     if COST_STORE.exists():
#         try:
#             return json.loads(COST_STORE.read_text(encoding="utf-8"))
#         except Exception:
#             pass
#     return {}

# def _save_costs(d):
#     COST_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

# def add_pending_transcribe_cost(collection_id: str, amount: float):
#     d = _load_costs()
#     node = d.setdefault(collection_id or "_default", {})
#     cur = float(node.get("pending_transcribe_cost", 0.0))
#     node["pending_transcribe_cost"] = round(cur + float(amount), 6)
#     _save_costs(d)

# def get_media_duration_sec(path: str) -> float:
#     """用 ffprobe 取得影音長度（秒）"""
#     out = subprocess.check_output(
#         ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
#     )
#     info = json.loads(out)
#     try:
#         return float(info.get("format", {}).get("duration", 0.0)) or 0.0
#     except Exception:
#         return 0.0
# # === end cost tracking ===

# # 清理工具（避免 Swagger 預設 "string" 亂入）
# def _clean_str(val: Optional[str]) -> Optional[str]:
#     if val is None:
#         return None
#     v = val.strip()
#     if not v or v.lower() in {"string", "null", "none", "undefined"}:
#         return None
#     return v


# async def _answer_from_url(url: str, top_k: int = 5, summary_query: str | None = None):
#     """
#     讀取 URL → 取正文 → 切段 → 向量化 → 建立臨時 collection → 用 doc 模式回答 → 清理臨時 collection
#     回傳格式與 /ask、/fetch_url 對齊。
#     """
#     # 1) 取文（沿用你現有的 _extract_text_from_url）
#     fulltext = _extract_text_from_url(url)

#     # 2) 清理 + 切段（沿用你在 fetch_url 的做法）
#     def approx_tokens(s: str) -> int:
#         return max(1, int(len(s) / 3.5))

#     def chunk_text(text: str, max_tokens_per_chunk: int = 400):
#         lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
#         chunks, cur, cur_tok = [], [], 0
#         for ln in lines:
#             t = approx_tokens(ln)
#             if cur_tok + t > max_tokens_per_chunk and cur:
#                 chunks.append("\n".join(cur))
#                 cur, cur_tok = [], 0
#             cur.append(ln)
#             cur_tok += t
#         if cur:
#             chunks.append("\n".join(cur))
#         return chunks

#     import re as _re
#     def light_clean(s: str) -> str:
#         s = _re.sub(r'\n{2,}', '\n', s)
#         s = _re.sub(r'(cookie|accept|privacy).{0,40}', '', s, flags=_re.I)
#         s = _re.sub(r'(terms|subscribe|sign in|login).{0,40}', '', s, flags=_re.I)
#         return s

#     cleaned = light_clean(fulltext)
#     segments = chunk_text(cleaned, max_tokens_per_chunk=400)

#     # 上限保護（最多 ~50k tokens）
#     HARD_MAX_TOKENS = 50000
#     kept, acc = [], 0
#     for s in segments:
#         t = approx_tokens(s)
#         if acc + t > HARD_MAX_TOKENS:
#             break
#         kept.append(s); acc += t

#     paragraphs = [{"page": 1, "text": s, "source": url} for s in kept]

#     # 3) 向量化
#     vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
#     if not vectors:
#         raise HTTPException(status_code=500, detail="向量產生失敗")
#     dim = len(vectors[0])

#     # 4) 臨時 collection
#     import hashlib
#     cid = "_url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
#     vector_store.reset_collection(cid, dim)
#     vector_store.add_embeddings(cid, vectors, paragraphs)

#     # 5) 問答（doc 模式）
#     user_query = summary_query or "請用上面網址內容條列重點並進行摘要"
#     answer, mode_used, meta = qna.answer_question(
#         query=user_query, top_k=top_k, mode="doc", sources=None, collection_id=cid
#     )

#     # 6) 清空臨時 collection（避免累積）
#     try:
#         vector_store.reset_collection(cid, dim)
#     except Exception:
#         pass

#     # 7) 回傳
#     return {
#         "ok": True,
#         "url": url,
#         "question": user_query,
#         "answer": answer,
#         "mode": mode_used,  # "doc"
#         "usage": meta.get("usage", {}),
#         "sources": meta.get("sources", []),
#         "cost_usd": round(meta.get("total_cost_usd", 0.0), 6),
#         "embedding_cost": round(meta.get("embedding_cost", 0.0), 6),
#         "chat_cost": round(meta.get("chat_cost", 0.0), 6),
#         "transcribe_cost": round(meta.get("transcribe_cost", 0.0), 6),
#         "collectionId": cid,
#     }


# @app.post("/fetch_url", summary="讀取網址內容並進行問答（不持久保存）")
# async def fetch_url(
#     url: str = Form(...),
#     query: str = Form("請用上面網址內容條列重點並進行摘要"),
#     top_k: int = Form(5),
# ):
#     try:
#         return await _answer_from_url(url, top_k=top_k, summary_query=query)
#     except HTTPException:
#         raise
#     except Exception:
#         raise HTTPException(status_code=500, detail=traceback.format_exc())



# @app.post("/upload", summary="上傳文件")
# async def upload_pdf(
#     request: Request,
#     file: UploadFile = File(...),
#     collectionId: str = Form(None),
#     mode: str = Form("overwrite"),
# ):
#     try:
#         # === 1) 驗證副檔名與上限 ===
#         ext_with_dot = Path(file.filename).suffix.lower()
#         if ext_with_dot not in ALLOWED_EXTS:
#             raise HTTPException(
#                 status_code=400,
#                 detail=f"不支援的檔案格式：{ext_with_dot}，可用：{', '.join(sorted(ALLOWED_EXTS))}"
#             )
#         ext = ext_with_dot.lstrip(".")
#         limit_mb = LIMITS_MB[ext]
#         limit_bytes = limit_mb * 1024 * 1024

#         # === 2) Content-Length 粗檢 ===
#         cl = request.headers.get("content-length")
#         if cl and int(cl) > int(limit_bytes * 1.2):
#             raise HTTPException(status_code=413, detail=f"檔案過大（上限 {limit_mb}MB）")

#         # === 3) 實際讀入檔案內容 ===
#         contents = await file.read()
#         if len(contents) > limit_bytes:
#             raise HTTPException(status_code=413, detail=f"檔案過大（上限 {limit_mb}MB）")

#         # === 4) 儲存檔案 ===
#         upload_dir = "data/uploads"
#         os.makedirs(upload_dir, exist_ok=True)
#         safe_name = os.path.basename(file.filename)
#         file_path = os.path.join(upload_dir, safe_name)
#         with open(file_path, "wb") as f:
#             f.write(contents)
#         await file.close()

#         fulltext, vision_cost = text_extractor.extract_any(file_path)

#         # === 6) 切段（改為包裝成頁面形式） ===
#         if not fulltext.strip():
#             raise HTTPException(status_code=500, detail="文件內容為空或解析失敗")

#         pages_text = [(1, fulltext)]   # ← 把整篇包成單頁
#         paragraphs = pdf_utils.split_into_paragraphs(pages_text)
#         if not paragraphs:
#             raise HTTPException(status_code=500, detail="切段失敗（可能內容過短或格式錯誤）")


#         # === 7) 向量化 ===
#         vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
#         if not vectors:
#             raise HTTPException(status_code=500, detail="向量產生失敗")
#         dim = len(vectors[0])

#         # === 8) collectionId 驗證與索引重建 ===
#         def _norm_collection_id(cid: str | None) -> str:
#             INVALID_VALUES = {"", "string", "null", "undefined", "none"}
#             if cid is None or cid.strip().lower() in INVALID_VALUES:
#                 return "_default"
#             cid = cid.strip()
#             import re
#             if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
#                 raise HTTPException(status_code=400, detail="非法的 collectionId")
#             return cid

#         cid = _norm_collection_id(collectionId)

#         # 模式選擇
#         if mode == "overwrite":
#             vector_store.reset_collection(cid, dim)
#         else:
#             vector_store.init_collection(cid, dim)

#         # === 9) 加入來源與儲存 ===
#         src = file.filename
#         for p in paragraphs:
#             p.setdefault("source", src)
#         vector_store.add_embeddings(cid, vectors, paragraphs)

#         # === 10) 影音轉錄費（Whisper 成本暫存） ===
#         is_audio = ext in {"mp3", "wav", "m4a"}
#         is_video = ext in {"mp4", "mov", "m4v"}

#         transcribe_cost = 0.0
#         if is_audio or is_video:
#             dur_sec = get_media_duration_sec(str(file_path))
#             minutes = dur_sec / 60.0
#             transcribe_cost = round(minutes * PRICE_WHISPER_PER_MIN, 6)
#             add_pending_transcribe_cost(cid, transcribe_cost)

#         # === 11) 成本統計 ===
#         embedding_cost = round(len(paragraphs) * 0.00001, 6)
#         total_cost = round(transcribe_cost + vision_cost + embedding_cost, 6)

#         # === 12) 回傳結果 ===
#         return {
#             "ok": True,
#             "message": f"已上傳並索引：{safe_name}",
#             "collectionId": cid,
#             "mode": mode,
#             "filetype": ext_with_dot,
#             "limit_mb": limit_mb,
#             "size_mb": round(len(contents) / (1024 * 1024), 2),
#             "paragraphs_indexed": len(paragraphs),
#             "transcribe_cost": transcribe_cost,
#             "vision_cost": vision_cost,
#             "embedding_cost": embedding_cost,
#             "total_cost_usd": total_cost,
#         }

#     except HTTPException:
#         raise
#     except Exception:
#         import traceback
#         detail = traceback.format_exc()
#         raise HTTPException(status_code=500, detail=detail)





        
# @app.post("/ask", summary="醫學問答查詢（支援純文字 / 純網址 / 網址+指令）")
# async def ask_question(
#     query: Optional[str] = Form(None),
#     url: Optional[str] = Form(None),
#     instruction: Optional[str] = Form(None),
#     top_k: int = Form(5),
#     source: Optional[List[str]] = Query(None),
#     collectionId: Optional[str] = Form(None),
# ):
#     """
#     支援：
#     1) 純文字：query="請解釋xxx"
#     2) 純網址：url="https://pmc...."
#     3) 網址+指令：
#        - 方式A：query="https://pmc.... 整理重點"
#        - 方式B：url="https://pmc...."  +  instruction="整理重點"
#     """
#     try:
#         # --- 清理 Swagger 預設值 ---
#         def _clean_str(val: Optional[str]) -> Optional[str]:
#             if val is None:
#                 return None
#             v = val.strip()
#             if not v or v.lower() in {"string", "null", "none", "undefined"}:
#                 return None
#             return v

#         query = _clean_str(query)
#         url = _clean_str(url)
#         instruction = _clean_str(instruction)
#         collectionId = _clean_str(collectionId)

#         cid = _norm_collection_id(collectionId)
#         sources = [s for s in (source or []) if s] or None
#         pure_text: Optional[str] = None

#         # --- 先拆網址與文字 ---
#         if url:
#             url = url.strip()
#             # 若不是合法網址，視為純文字問題
#             if not URL_RE.match(url):
#                 merged = " ".join(x for x in [(query or ""), url, (instruction or "")] if x).strip()
#                 pure_text = merged or None
#                 url = None
#                 instruction = None
#         elif query:
#             q = query.strip()
#             u, inst = _split_url_and_instruction(q)
#             if u:
#                 url = u
#                 instruction = instruction or inst
#             else:
#                 pure_text = q
#         else:
#             raise HTTPException(status_code=400, detail="缺少 query 或 url")

#         # --- 分支處理 ---
#         if url:
#             # ✅ 真的抓網址內容並回答
#             return await _answer_from_url(
#                 url,
#                 top_k=top_k,
#                 summary_query=instruction or "請用上面網址內容條列重點並進行摘要",
#             )

#         # ✅ 純文字情境
#         answer, mode_used, meta = qna.answer_question(
#             query=pure_text,
#             top_k=top_k,
#             mode="doc" if (sources or cid) else "general",
#             sources=sources,
#             collection_id=cid,
#         )

#         return {
#             "ok": True,
#             "collectionId": cid or meta.get("collection_id"),
#             "question": pure_text,
#             "answer": answer,
#             "mode": mode_used,
#             "cost_usd": round(meta.get("total_cost_usd", 0.0), 6),
#             "embedding_cost": round(meta.get("embedding_cost", 0.0), 6),
#             "chat_cost": round(meta.get("chat_cost", 0.0), 6),
#             "transcribe_cost": round(meta.get("transcribe_cost", 0.0), 6),
#             "usage": meta.get("usage", {}),
#             "sources": meta.get("sources", []) or (sources or []),
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



#     # .\.venv\Scripts\Activate.ps1           # （備忘）再次提醒啟動虛擬環境
#     # python -m uvicorn app:app              # （備忘）再次提醒啟動伺服器指令


from dotenv import load_dotenv            # 從 python-dotenv 載入讀取 .env 檔案的函式，用來把 .env 裡的金鑰、價格等設定載入環境變數
load_dotenv()                             # 讀取當前目錄或上層的 .env，將環境變數載入到 os.environ（供後面 os.getenv 使用）

import os                                  # 作業系統相關（路徑、環境變數、檔案操作）
import traceback                           # 取得完整例外堆疊字串，方便在開發時回傳詳細錯誤
from fastapi import FastAPI, File, UploadFile, HTTPException, Form  # FastAPI 主體與請求/例外/表單工具
from fastapi.middleware.cors import CORSMiddleware                  # CORS 中介層，讓前端（不同網域，例如 Flutter App）可呼叫 API

# ---- 專案內部服務與模組 ----
from services import text_extractor  # 負責「任何類型」檔案抽文字 + 圖片/影片的 vision 分析成本回傳
from services import pdf_utils, vector_store, qna  # pdf_utils: 切段工具；vector_store: 向量索引；qna: 問答核心邏輯
from routers.knowledge import router as knowledge_router  # /knowledge 路由（管理知識庫 / collections）

from services import text_extractor  # 重複 import（雖然不影響執行，但其實可以刪掉；這邊我先保留不動）
import requests                      # 用來對外部網址發 HTTP 請求（抓網頁 HTML）
from bs4 import BeautifulSoup        # 解析 HTML，萃取純文字內容
from urllib.parse import urlparse    # 拆解網址（確認 scheme 是 http/https）
import re                            # 正規表示式，用來偵測網址與驗證 collectionId 格式
from pathlib import Path             # 路徑物件操作，比 os.path 好用
from fastapi import Request, Query   # Request 用來取 header；Query 用來接收 Query String 參數
from typing import List, Optional    # 型別註記用


from routers import news_api
from routers.news_api import router as news_router, refresh_who_news

from routers import find_papers



# ==========================
# FastAPI 應用與基本設定
# ==========================

# （舊版：曾經在這邊初始化向量庫，現在改成在別處處理）
# vector_store.init_index(1536)  # OpenAI ada-002 向量長度 dotenv

# .\.venv\Scripts\Activate.ps1              # （備忘）啟動虛擬環境的 PowerShell 指令
# python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000   # （備忘）啟動開發伺服器
# http://127.0.0.1:8000/docs               # （備忘）Swagger UI 文件入口 
#  deactivate 

app = FastAPI(                             # 建立 FastAPI 應用實例
    title="Medical QA Backend",            # 顯示在 /docs Swagger UI 頁面的標題
    description="上傳醫學PDF並進行問答的後端服務",  # 顯示在 /docs 的描述文字
    version="0.1.0"                        # API 版本號
)

# 允許上傳的副檔名集合（有點像白名單）
ALLOWED_EXTS = {
    ".txt", ".html", ".htm", ".pdf", ".docx", ".pptx",
    ".mp3", ".wav", ".m4a", ".mp4", ".mov", ".m4v",
    ".jpg", ".jpeg", ".png", ".bmp",
}

# 每種檔案類型對應的最大上傳大小（MB 單位）
LIMITS_MB = {
    # 純文字
    "txt": 5, "html": 5, "htm": 5,
    # PDF / Office 文件
    "pdf": 25, "docx": 25, "pptx": 25,
    # 音訊
    "mp3": 50, "wav": 50, "m4a": 50,
    # 影片
    "mp4": 100, "mov": 100, "m4v": 100,
    # 圖片
    "jpg": 10, "jpeg": 10, "png": 10, "bmp": 10,
}

# 掛載 /knowledge 相關的路由（例如：列出 collections、刪除 collection 等）
app.include_router(knowledge_router)
app.include_router(news_router)
app.include_router(find_papers.router)

# 加入 CORS 中介層，讓前端（例如：你在手機上的 Flutter App、本機 Web）可以跨網域呼叫 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 目前先開放全部來源；正式環境建議改成你的網域白名單
    allow_methods=["*"],        # 允許所有 HTTP 方法（GET/POST/PUT/DELETE 等）
    allow_headers=["*"],        # 允許所有自訂標頭
)

# ==========================
# 啟動時預先抓一次 WHO 快訊
# ==========================
@app.on_event("startup")
def preload_news():
    try:
        # 預抓 20 則，直接翻成繁中，存在 NEWS_CACHE 裡
        refresh_who_news(limit=20, target_lang="zh-TW")
        print("[NEWS] 伺服器啟動時已預抓 WHO 快訊")
    except Exception as e:
        # 就算失敗也不要讓整個 app 掛掉，只是印 log
        print(f"[NEWS] 啟動時預抓 WHO 快訊失敗: {e}")

# ==========================
# 共用工具：網址與字串處理
# ==========================

# 用正規表示式偵測網址（最簡單版，找到第一個 http/https 開頭的字串）
URL_RE = re.compile(r"https?://[^\s]+")


def _norm_collection_id(cid: Optional[str]) -> Optional[str]:
    """
    將前端傳來的 collectionId 做標準化處理：
    - 去掉空字串、"string"、"null" 等 Swagger 預設垃圾值
    - 驗證只能包含 英數、底線、減號，長度 1~64
    - 若不合法則丟出 400 錯誤
    """
    INVALID_VALUES = {"", "string", "null", "undefined", "none"}
    if cid is None or cid.strip().lower() in INVALID_VALUES:
        return None
    cid = cid.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
        raise HTTPException(status_code=400, detail="非法的 collectionId")
    return cid


def _split_url_and_instruction(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    從一段文字中抓出「第一個 URL」，剩下的文字視為使用者說明（instruction）。
    例如：
        "https://xxx 請幫我條列重點"
    會被拆成：
        url="https://xxx"
        instruction="請幫我條列重點"
    """
    m = URL_RE.search(text)
    if not m:
        # 沒有網址，就整段視為純問題文字
        return None, text.strip() or None

    url = m.group(0)
    # 把第一個網址前後的文字合併起來當作 instruction
    inst = (text[:m.start()] + text[m.end():]).strip()
    return url, (inst if inst else None)


# ==========================
# 處理「給網址 → 抓內容文字」的工具
# ==========================

def _extract_text_from_url(url: str, timeout: int = 12) -> str:
    """
    下載 HTML，移除 script/style 等無用內容，回傳乾淨文字。
    主要用在：
      - /fetch_url
      - /ask 當 query 含有網址時
    """
    # 基本網址驗證（只接受 http/https）
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="只支援 http/https 網址")

    # 嘗試下載網頁內容
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Medical-QA/1.0)"},
        )
    except requests.RequestException as e:
        # 連線問題（DNS、timeout、連線被拒絕等）
        raise HTTPException(status_code=400, detail=f"連線失敗：{e}")

    if resp.status_code != 200:
        # 4xx、5xx 等錯誤
        raise HTTPException(status_code=400, detail=f"無法讀取網址（HTTP {resp.status_code}）")

    # 檢查 Content-Type，避免抓到 PDF 等非 HTML 內容
    ctype = (resp.headers.get("Content-Type") or "").lower()

    # 目前只允許 HTML 類型內容；其餘請改用 /upload 上傳檔案
    if not any(t in ctype for t in ["text/html", "text/plain", "application/xhtml"]):
        raise HTTPException(
            status_code=415,
            detail=f"目前僅支援一般網頁文字，偵測到 Content-Type={ctype}，請改用 /upload 上傳檔案。"
        )

    # 粗略大小限制（避免下載超巨網頁，拖爆記憶體）
    if len(resp.content) > 2 * 1024 * 1024:  # 2MB
        raise HTTPException(status_code=413, detail="頁面過大（>2MB），請改上傳檔案或提供摘要。")

    # 使用 BeautifulSoup 解析 HTML → 純文字
    soup = BeautifulSoup(resp.text, "html.parser")
    # 移除 script / style / noscript 等無內容元素
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()

    text = soup.get_text(separator="\n", strip=True)

    # 簡單整理每一行，移除空行
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join([ln for ln in lines if ln])

    if len(text) < 100:
        # 文字太少，可能是首頁或廣告頁，對 QA 沒什麼用
        raise HTTPException(status_code=400, detail="頁面文字過少或非文章頁，無法分析。")

    return text


# ==========================
# 成本追蹤：Whisper 影音轉錄費
# ==========================
import os, json, subprocess
from pathlib import Path

# 每分鐘轉錄費用（從 .env 讀，如果沒設就用 0.006 USD/min）
PRICE_WHISPER_PER_MIN = float(os.getenv("PRICE_WHISPER_PER_MIN", "0.006"))

# 成本紀錄檔案路徑：data/costs.json
COST_STORE = Path("data") / "costs.json"
COST_STORE.parent.mkdir(parents=True, exist_ok=True)  # 確保資料夾存在


def _load_costs():
    """
    從 JSON 檔載入成本資訊（per collection），格式大致為：
      {
        "某個collectionId": {
          "pending_transcribe_cost": 0.0123,
          ...
        },
        ...
      }
    """
    if COST_STORE.exists():
        try:
            return json.loads(COST_STORE.read_text(encoding="utf-8"))
        except Exception:
            # 壞掉就當作空資料
            pass
    return {}


def _save_costs(d):
    """把成本字典寫回 JSON 檔"""
    COST_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def add_pending_transcribe_cost(collection_id: str, amount: float):
    """
    將某個 collection 的「待確認轉錄費用」累加：
    - collection_id: 目前索引的 collection
    - amount: 新增的轉錄成本
    這是用來事後與實際 Whisper 呼叫成本對帳用。
    """
    d = _load_costs()
    node = d.setdefault(collection_id or "_default", {})
    cur = float(node.get("pending_transcribe_cost", 0.0))
    node["pending_transcribe_cost"] = round(cur + float(amount), 6)
    _save_costs(d)


def get_media_duration_sec(path: str) -> float:
    """
    使用 ffprobe 取得影音長度（秒）。
    前提：系統有安裝 ffmpeg/ffprobe。
    """
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    )
    info = json.loads(out)
    try:
        return float(info.get("format", {}).get("duration", 0.0)) or 0.0
    except Exception:
        return 0.0
# === end cost tracking ===


# ==========================
# 共用字串清理工具
# ==========================

def _clean_str(val: Optional[str]) -> Optional[str]:
    """
    清理前端送來的字串：
    - None 直接回 None
    - 去掉前後空白
    - 若變成空字串或 "string"/"null"/"none"/"undefined" → 回傳 None
    主要是為了清掉 Swagger 預設值 "string" 之類的垃圾。
    """
    if val is None:
        return None
    v = val.strip()
    if not v or v.lower() in {"string", "null", "none", "undefined"}:
        return None
    return v


# ==========================
# 核心：給網址 → 建立臨時 collection → QA
# ==========================

async def _answer_from_url(url: str, top_k: int = 5, summary_query: str | None = None):
    """
    讀取 URL → 取正文 → 切段 → 向量化 → 建立「臨時 collection」→ 用 doc 模式回答 → 清理臨時 collection。

    回傳格式與 /ask、/fetch_url 對齊，會包含：
      - answer: 模型回答
      - mode: 使用的模式（"doc"）
      - usage / sources / cost 細節
    """
    # 1) 先抓網址全文（純文字）
    fulltext = _extract_text_from_url(url)

    # 2) 清理 + 切段：把長文切成多段（類似你在 /upload 用的做法，但這裡用內嵌版本）
    def approx_tokens(s: str) -> int:
        # 粗估 token 數：字數 / 3.5（只是估算，避免切段太大）
        return max(1, int(len(s) / 3.5))

    def chunk_text(text: str, max_tokens_per_chunk: int = 400):
        # 用行為單位來切，避免切到一半的句子
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        chunks, cur, cur_tok = [], [], 0
        for ln in lines:
            t = approx_tokens(ln)
            # 若加入這一行會超過上限，先把目前累積的 chunk 收起來
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
        """
        針對網頁文字做一些輕度清理：
        - 合併多個連續換行
        - 去除 cookie/accept/privacy/terms/login 等無關提示文字
        """
        s = _re.sub(r'\n{2,}', '\n', s)
        s = _re.sub(r'(cookie|accept|privacy).{0,40}', '', s, flags=_re.I)
        s = _re.sub(r'(terms|subscribe|sign in|login).{0,40}', '', s, flags=_re.I)
        return s

    cleaned = light_clean(fulltext)
    segments = chunk_text(cleaned, max_tokens_per_chunk=400)

    # 3) 做一個「總 token 上限」保護，避免某些超長文章爆炸
    HARD_MAX_TOKENS = 50000
    kept, acc = [], 0
    for s in segments:
        t = approx_tokens(s)
        if acc + t > HARD_MAX_TOKENS:
            break
        kept.append(s)
        acc += t

    # 轉成與 PDF 切段類似的結構（有 page、text、source）
    paragraphs = [{"page": 1, "text": s, "source": url} for s in kept]

    # 4) 向量化（呼叫 qna 內的 embed_paragraphs，最終會用 embeddings 存入向量庫）
    vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
    if not vectors:
        raise HTTPException(status_code=500, detail="向量產生失敗")
    dim = len(vectors[0])

    # 5) 建立一個「臨時 collection」（針對這個 url），用 hash 當 name
    import hashlib
    cid = "_url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

    # reset_collection：確保這個臨時 collection 是乾淨的
    vector_store.reset_collection(cid, dim)
    vector_store.add_embeddings(cid, vectors, paragraphs)

    # 6) 做一次 QA（doc 模式），問題就是 summary_query 或預設「請用上面網址內容條列重點並進行摘要」
    user_query = summary_query or "請用上面網址內容條列重點並進行摘要"
    answer, mode_used, meta = qna.answer_question(
        query=user_query, top_k=top_k, mode="doc", sources=None, collection_id=cid
    )

    # 7) 用完就把臨時 collection 清掉，避免向量庫越積越多
    try:
        vector_store.reset_collection(cid, dim)
    except Exception:
        # 若清理失敗就算了，這裡不再往外丟
        pass

    # 8) 回傳結果給前端（/docs 也會照這個格式顯示）
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


# ==========================
# API：/fetch_url
# - 直接給網址 → 幫你抓內容並問答
# ==========================

@app.post("/fetch_url", summary="讀取網址內容並進行問答（不持久保存）")
async def fetch_url(
    url: str = Form(...),  # 表單欄位：網址
    query: str = Form("請用上面網址內容條列重點並進行摘要"),  # 問題（可改寫成想問的內容）
    top_k: int = Form(5),  # 從向量庫取前幾名相似段落
):
    try:
        # 直接重用上面的 _answer_from_url
        return await _answer_from_url(url, top_k=top_k, summary_query=query)
    except HTTPException:
        # 已經處理過的 HTTPException 直接再丟出讓 FastAPI 處理
        raise
    except Exception:
        # 其他非預期錯誤，回傳 500 + 例外堆疊方便除錯
        raise HTTPException(status_code=500, detail=traceback.format_exc())


# ==========================
# API：/upload
# - 上傳 PDF/Word/PPT/音訊/影片/圖片，解析並寫入向量庫
# ==========================

@app.post("/upload", summary="上傳文件")
async def upload_pdf(
    request: Request,                     # 可以取得 header（例如 Content-Length）
    file: UploadFile = File(...),        # 上傳檔案
    collectionId: str = Form(None),      # 指定存入哪個 collection（資料夾/知識庫）
    mode: str = Form("overwrite"),       # "overwrite"：清空舊資料；其他：append
):
    try:
        # === 1) 驗證副檔名與上限 ===
        ext_with_dot = Path(file.filename).suffix.lower()  # 取副檔名（包含 .）
        if ext_with_dot not in ALLOWED_EXTS:
            # 不在白名單就直接拒絕
            raise HTTPException(
                status_code=400,
                detail=f"不支援的檔案格式：{ext_with_dot}，可用：{', '.join(sorted(ALLOWED_EXTS))}"
            )
        ext = ext_with_dot.lstrip(".")   # 不帶點的版本，例如 ".pdf" → "pdf"
        limit_mb = LIMITS_MB[ext]        # 取出該類型對應的上限（MB）
        limit_bytes = limit_mb * 1024 * 1024

        # === 2) Content-Length 粗檢 ===
        # 有些瀏覽器/前端會在 header 帶 content-length，可以先粗略擋一次
        cl = request.headers.get("content-length")
        if cl and int(cl) > int(limit_bytes * 1.2):
            # 留一點彈性（1.2 倍），避免因為 multipart overhead 被誤殺
            raise HTTPException(status_code=413, detail=f"檔案過大（上限 {limit_mb}MB）")

        # === 3) 實際讀入檔案內容 ===
        contents = await file.read()
        if len(contents) > limit_bytes:
            # 真正超過就擋掉
            raise HTTPException(status_code=413, detail=f"檔案過大（上限 {limit_mb}MB）")

        # === 4) 儲存檔案到本機資料夾 ===
        upload_dir = "data/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(file.filename)  # 避免有人傳路徑進來
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(contents)
        await file.close()

        # === 5) 抽取文字 + 可能的 vision 成本 ===
        # text_extractor.extract_any 會根據副檔名自動決定用哪種方式解析文字
        # 回傳：fulltext（整份文字）、vision_cost（圖片/影片分析成本）
        fulltext, vision_cost = text_extractor.extract_any(file_path)

        # === 6) 切段（改為包裝成頁面形式） ===
        if not fulltext.strip():
            raise HTTPException(status_code=500, detail="文件內容為空或解析失敗")

        # 目前簡單地把整份當成一頁：[(頁碼, 文字)]
        pages_text = [(1, fulltext)]
        # 用 pdf_utils.split_into_paragraphs 依空行、長度等切出多個段落
        paragraphs = pdf_utils.split_into_paragraphs(pages_text)
        if not paragraphs:
            raise HTTPException(status_code=500, detail="切段失敗（可能內容過短或格式錯誤）")

        # === 7) 向量化 ===
        # 把每個段落文字轉成 embedding 向量
        vectors = qna.embed_paragraphs([p["text"] for p in paragraphs])
        if not vectors:
            raise HTTPException(status_code=500, detail="向量產生失敗")
        dim = len(vectors[0])  # 向量維度，例如 1536

        # === 8) collectionId 驗證與索引重建 ===
        # 這裡再定義一個區域版的 _norm_collection_id（與全域的幾乎一樣）
        def _norm_collection_id(cid: str | None) -> str:
            INVALID_VALUES = {"", "string", "null", "undefined", "none"}
            if cid is None or cid.strip().lower() in INVALID_VALUES:
                # 若沒指定，就用 "_default" 當預設 collection
                return "_default"
            cid = cid.strip()
            import re
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", cid):
                raise HTTPException(status_code=400, detail="非法的 collectionId")
            return cid

        cid = _norm_collection_id(collectionId)

        # 模式選擇：
        # - overwrite：整個 collection 重新建立（清空舊內容）
        # - 其他：如果已存在，就延用原本索引
        if mode == "overwrite":
            vector_store.reset_collection(cid, dim)
        else:
            vector_store.init_collection(cid, dim)

        # === 9) 加入來源資訊並寫入向量庫 ===
        src = file.filename
        for p in paragraphs:
            # 如果 paragraph 沒有 source，就幫它加上檔名
            p.setdefault("source", src)

        # 把 vectors + paragraphs 一起寫入 collection
        vector_store.add_embeddings(cid, vectors, paragraphs)

        # === 10) 影音轉錄費（Whisper 成本暫存） ===
        is_audio = ext in {"mp3", "wav", "m4a"}
        is_video = ext in {"mp4", "mov", "m4v"}

        transcribe_cost = 0.0
        if is_audio or is_video:
            # 取得影音長度（秒）→ 換算成分鐘 → 計算暫存轉錄成本
            dur_sec = get_media_duration_sec(str(file_path))
            minutes = dur_sec / 60.0
            transcribe_cost = round(minutes * PRICE_WHISPER_PER_MIN, 6)
            # 先累加到 pending 欄位，之後你可以再對帳
            add_pending_transcribe_cost(cid, transcribe_cost)

        # === 11) 成本統計（粗略計算 embedding 數量成本 + vision 成本 + 轉錄成本） ===
        embedding_cost = round(len(paragraphs) * 0.00001, 6)  # 這個數字是你自己估的單段 embedding 成本
        total_cost = round(transcribe_cost + vision_cost + embedding_cost, 6)

        # === 12) 回傳結果給前端 ===
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
        # 已知錯誤直接往外丟，讓 FastAPI 用對應 status_code 回應
        raise
    except Exception:
        # 未預期錯誤：抓完整堆疊方便你在前端/debug 看到
        import traceback
        detail = traceback.format_exc()
        raise HTTPException(status_code=500, detail=detail)


# ==========================
# API：/ask
# - 支援：
#   1) 純文字提問
#   2) 純網址
#   3) 「網址 + 指令」組合
# ==========================

@app.post("/ask", summary="醫學問答查詢（支援純文字 / 純網址 / 網址+指令）")
async def ask_question(
    query: Optional[str] = Form(None),          # 一般問題或「含網址的文字」
    url: Optional[str] = Form(None),           # 單獨提供網址用
    instruction: Optional[str] = Form(None),   # 若 url 另外提供，就當作補充指令
    top_k: int = Form(5),
    source: Optional[List[str]] = Query(None), # 指定只從哪些來源檔案過濾
    collectionId: Optional[str] = Form(None),  # 指定 collection
):
    """
    支援三種使用方式：

    1) 純文字：
       - query="請解釋xxx"
       → 視為一般問答（可能用 general 模式或 doc 模式）

    2) 純網址：
       - url="https://pmc...."
       → 會抓取網頁內容、建立臨時 collection、做摘要或回答

    3) 網址 + 指令：
       - 方式A：query="https://pmc.... 整理重點"
       - 方式B：url="https://pmc...." + instruction="整理重點"
    """
    try:
        # --- 再次覆寫本地版 _clean_str（邏輯與全域版本雷同） ---
        def _clean_str(val: Optional[str]) -> Optional[str]:
            if val is None:
                return None
            v = val.strip()
            if not v or v.lower() in {"string", "null", "none", "undefined"}:
                return None
            return v

        # 先把 Swagger 預設 "string"、空白等清乾淨
        query = _clean_str(query)
        url = _clean_str(url)
        instruction = _clean_str(instruction)
        collectionId = _clean_str(collectionId)

        # collection 處理：如果是空字串/null 就變成 None（交給 qna 內部決定預設）
        cid = _norm_collection_id(collectionId)
        # sources：過濾掉空字串
        sources = [s for s in (source or []) if s] or None
        pure_text: Optional[str] = None

        # --- 先拆網址與文字 ---
        if url:
            # 若有提供 url 欄位：
            url = url.strip()
            # 如果 url 欄位內容不是合法網址，就把它當成文字問題
            if not URL_RE.match(url):
                merged = " ".join(x for x in [(query or ""), url, (instruction or "")] if x).strip()
                pure_text = merged or None
                url = None
                instruction = None
        elif query:
            # 沒有 url 欄位，但 query 有東西 → 檢查裡面有沒有網址
            q = query.strip()
            u, inst = _split_url_and_instruction(q)
            if u:
                # 如果有偵測到網址，就拆成網址 + 指令
                url = u
                instruction = instruction or inst
            else:
                # 沒有網址 → 純文字問題
                pure_text = q
        else:
            # 兩個都沒有就直接報錯
            raise HTTPException(status_code=400, detail="缺少 query 或 url")

        # --- 分支處理：若有 url，就走「抓網址 + QA」路線 ---
        if url:
            # 呼叫前面寫好的 _answer_from_url，會建立臨時 collection 做 QA
            return await _answer_from_url(
                url,
                top_k=top_k,
                summary_query=instruction or "請用上面網址內容條列重點並進行摘要",
            )

        # --- 純文字情境：走一般問答（可以搭配 collection + sources） ---
        answer, mode_used, meta = qna.answer_question(
            query=pure_text,
            top_k=top_k,
            # 若有指定 sources 或 cid，就用 doc 模式（從向量庫檢索）
            # 否則用 general 模式（純 LLM 一般知識）
            mode="doc" if (sources or cid) else "general",
            sources=sources,
            collection_id=cid,
        )

        # 統一回傳格式
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
        # 其他錯誤（例如 qna 內部錯誤），先簡單轉成字串
        raise HTTPException(status_code=500, detail=str(e))


    # .\.venv\Scripts\Activate.ps1           
    # python -m uvicorn app:app             
