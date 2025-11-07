# # === vector_store.py ===
# from __future__ import annotations
# import os, json
# from pathlib import Path
# import faiss
# import numpy as np

# BASE_DIR = Path("data/collections")
# BASE_DIR.mkdir(parents=True, exist_ok=True)

# # 以記憶體快取各 collection 的索引與中繼資料
# _COLLECTIONS: dict[str, dict] = {}  
# # 結構：
# # {
# #   "myCollection": {
# #       "index": faiss.Index,
# #       "dim": 3072,
# #       "meta": [{"text": "...", "source": "...", "time": ...}, ...],
# #   },
# #   ...
# # }

# def _paths(cid: str):
#     root = BASE_DIR / cid
#     return {
#         "root": root,
#         "index": root / "index.faiss",
#         "meta":  root / "meta.json",
#     }

# def _load_collection(cid: str):
#     p = _paths(cid)
#     p["root"].mkdir(parents=True, exist_ok=True)
#     meta = []
#     if p["meta"].exists():
#         try:
#             meta = json.loads(p["meta"].read_text(encoding="utf-8"))
#         except Exception:
#             meta = []
#     index = None
#     if p["index"].exists():
#         index = faiss.read_index(str(p["index"]))
#     return index, meta

# def _save_collection(cid: str):
#     obj = _COLLECTIONS.get(cid)
#     if not obj:
#         return
#     p = _paths(cid)
#     p["root"].mkdir(parents=True, exist_ok=True)
#     if obj.get("index") is not None:
#         faiss.write_index(obj["index"], str(p["index"]))
#     p["meta"].write_text(json.dumps(obj.get("meta", []), ensure_ascii=False, indent=2), encoding="utf-8")

# def list_collections() -> list[str]:
#     return [d.name for d in BASE_DIR.iterdir() if d.is_dir()]

# def ensure_collection(cid: str, dim: int | None = None):
#     """載入或建立 collection；當沒有 index 且提供 dim 時會新建。"""
#     obj = _COLLECTIONS.get(cid)
#     if obj:
#         return obj
#     index, meta = _load_collection(cid)
#     if index is None and dim is not None:
#         index = faiss.IndexFlatL2(dim)
#     if index is None:
#         # 尚未建立過索引，先用佔位；等第一次 add_embeddings 時才建
#         obj = {"index": None, "dim": dim, "meta": meta}
#     else:
#         obj = {"index": index, "dim": index.d, "meta": meta}
#     _COLLECTIONS[cid] = obj
#     return obj

# def reset_collection(cid: str, dim: int):
#     """清空並重建 collection（覆蓋式）"""
#     obj = {"index": faiss.IndexFlatL2(dim), "dim": dim, "meta": []}
#     _COLLECTIONS[cid] = obj
#     _save_collection(cid)

# def init_collection(cid: str, dim: int):
#     """累積式使用：若無索引就建，若已有就沿用"""
#     obj = ensure_collection(cid, dim)
#     if obj["index"] is None:
#         obj["index"] = faiss.IndexFlatL2(dim)
#         obj["dim"] = dim
#         _save_collection(cid)

# def add_embeddings(cid: str, vectors: list[list[float]] | np.ndarray, metas: list[dict]):
#     obj = ensure_collection(cid)
#     if obj["index"] is None:
#         # 第一次加入向量時才確定 dim
#         dim = len(vectors[0])
#         obj["index"] = faiss.IndexFlatL2(dim)
#         obj["dim"] = dim
#     arr = np.asarray(vectors, dtype="float32")
#     if arr.shape[1] != obj["dim"]:
#         raise ValueError(f"Dimension mismatch: vec {arr.shape[1]} vs index {obj['dim']}")
#     obj["index"].add(arr)
#     obj["meta"].extend(metas)
#     _save_collection(cid)

# def search(cid: str, query_vec: list[float], top_k: int = 5, sources: list[str] | None = None):
#     obj = ensure_collection(cid)
#     if obj["index"] is None or obj["index"].ntotal == 0:
#         return []
#     q = np.asarray([query_vec], dtype="float32")
#     D, I = obj["index"].search(q, top_k * 3)  # 先抓多一點做過濾
#     hits = []
#     meta = obj["meta"]
#     for idx in I[0]:
#         if idx < 0 or idx >= len(meta):
#             continue
#         m = meta[idx]
#         if sources and m.get("source") not in sources:
#             continue
#         hits.append(m)
#         if len(hits) >= top_k:
#             break
#     return hits

# vector_store.py
# ---------------------------------------------
# 這是醫學問答系統的「向量庫管理模組」。
# 功能：
# 1️⃣ 為每個 collection 建立 / 載入 / 儲存向量索引（faiss.IndexFlatL2）
# 2️⃣ 儲存每段文字（paragraph）的 meta 資訊（來源檔名、頁碼等）
# 3️⃣ 提供新增向量 (add_embeddings) 與相似度搜尋 (search)
# 4️⃣ 資料結構為每個 collection 一個資料夾：
#      data/collections/<collection_id>/
#        ├── index.faiss   ← 向量資料
#        └── meta.json     ← 段落描述列表
# ---------------------------------------------

from __future__ import annotations
import os, json
from pathlib import Path
import faiss                # Facebook AI 相似度搜尋庫
import numpy as np

# === 基本資料夾設定 ===
# 所有 collection 都放在 data/collections/<cid>/
BASE_DIR = Path("data/collections")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# 快取所有載入過的 collection，避免每次重複讀檔
_COLLECTIONS: dict[str, dict] = {}
# 結構範例：
# {
#   "myCollection": {
#       "index": faiss.IndexFlatL2,
#       "dim": 1536,
#       "meta": [{"page": 1, "text": "...", "source": "..."}],
#   },
#   ...
# }


# ==========================
# 共用：路徑工具
# ==========================
def _paths(cid: str):
    """給定 collectionId，回傳對應資料夾及檔案路徑。"""
    root = BASE_DIR / cid
    return {
        "root": root,
        "index": root / "index.faiss",   # 向量索引檔
        "meta":  root / "meta.json",     # 段落中繼資料檔
    }


# ==========================
# 載入與儲存
# ==========================
def _load_collection(cid: str):
    """
    載入指定 collection：
    - 嘗試從磁碟讀取 index.faiss 與 meta.json。
    - 若沒有檔案，就回傳 (None, [])。
    """
    p = _paths(cid)
    p["root"].mkdir(parents=True, exist_ok=True)

    # 讀取 meta.json（段落中繼資料）
    meta = []
    if p["meta"].exists():
        try:
            meta = json.loads(p["meta"].read_text(encoding="utf-8"))
        except Exception:
            meta = []

    # 讀取 FAISS 向量索引
    index = None
    if p["index"].exists():
        index = faiss.read_index(str(p["index"]))

    return index, meta


def _save_collection(cid: str):
    """
    儲存指定 collection：
    - 將 index.faiss 與 meta.json 寫回磁碟。
    - 若該 collection 尚未初始化則略過。
    """
    obj = _COLLECTIONS.get(cid)
    if not obj:
        return

    p = _paths(cid)
    p["root"].mkdir(parents=True, exist_ok=True)

    # 寫入 FAISS index
    if obj.get("index") is not None:
        faiss.write_index(obj["index"], str(p["index"]))

    # 寫入 meta.json
    p["meta"].write_text(
        json.dumps(obj.get("meta", []), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ==========================
# Collection 管理
# ==========================
def list_collections() -> list[str]:
    """列出目前存在的所有 collection 資料夾名稱。"""
    return [d.name for d in BASE_DIR.iterdir() if d.is_dir()]


def ensure_collection(cid: str, dim: int | None = None):
    """
    確保 collection 已載入。
    若記憶體中沒有：
      → 從磁碟讀取 index.faiss + meta.json。
    若 index 不存在但提供了 dim：
      → 新建空的 IndexFlatL2(dim)。

    回傳：
      {
        "index": faiss.Index 或 None,
        "dim": 向量維度,
        "meta": 段落列表
      }
    """
    obj = _COLLECTIONS.get(cid)
    if obj:
        return obj

    # 從磁碟讀
    index, meta = _load_collection(cid)

    # 若沒有索引但有給維度 → 新建
    if index is None and dim is not None:
        index = faiss.IndexFlatL2(dim)

    # 若都沒有，就留空等第一次 add_embeddings 時才建
    if index is None:
        obj = {"index": None, "dim": dim, "meta": meta}
    else:
        obj = {"index": index, "dim": index.d, "meta": meta}

    _COLLECTIONS[cid] = obj
    return obj


def reset_collection(cid: str, dim: int):
    """
    重建 collection（覆蓋舊資料）：
    - 建立新的空 index
    - 清空 meta
    - 立即儲存到磁碟
    """
    obj = {"index": faiss.IndexFlatL2(dim), "dim": dim, "meta": []}
    _COLLECTIONS[cid] = obj
    _save_collection(cid)


def init_collection(cid: str, dim: int):
    """
    初始化 collection：
    - 若該 collection 尚未建立，就新建一個空索引
    - 若已存在，就保留現有索引（累積模式）
    """
    obj = ensure_collection(cid, dim)
    if obj["index"] is None:
        obj["index"] = faiss.IndexFlatL2(dim)
        obj["dim"] = dim
        _save_collection(cid)


# ==========================
# 向量新增
# ==========================
def add_embeddings(cid: str, vectors: list[list[float]] | np.ndarray, metas: list[dict]):
    """
    將多個向量（vectors）及其對應的 meta（段落資訊）加入指定 collection。

    - 若 collection 尚未建立，會自動建立 IndexFlatL2。
    - 每次新增都會同步更新 meta.json。
    - 維度不符會拋出 ValueError。
    """
    obj = ensure_collection(cid)

    # 若第一次新增 → 新建 index
    if obj["index"] is None:
        dim = len(vectors[0])
        obj["index"] = faiss.IndexFlatL2(dim)
        obj["dim"] = dim

    arr = np.asarray(vectors, dtype="float32")

    # 維度檢查
    if arr.shape[1] != obj["dim"]:
        raise ValueError(f"Dimension mismatch: vec {arr.shape[1]} vs index {obj['dim']}")

    # 實際加入向量
    obj["index"].add(arr)
    obj["meta"].extend(metas)

    _save_collection(cid)


# ==========================
# 相似度搜尋
# ==========================
def search(cid: str, query_vec: list[float], top_k: int = 5, sources: list[str] | None = None):
    """
    在指定 collection 中搜尋最相似的段落。

    參數：
      - cid：collection 名稱
      - query_vec：查詢向量（由使用者 query embedding 產出）
      - top_k：最多取幾個結果
      - sources：若指定，只從特定檔案來源過濾（如「只搜尋某個文件」）

    回傳：
      List[Dict]，每項為一個段落 meta，例如：
        {
          "page": 2,
          "text": "本文指出心肌梗塞的臨床診斷應...",
          "source": "NEJM_heart.pdf",
          "score": 0.87
        }
    """
    obj = ensure_collection(cid)

    # 若還沒建立 index 或裡面沒資料 → 回傳空列表
    if obj["index"] is None or obj["index"].ntotal == 0:
        return []

    # 把查詢向量包成 batch 形式（1×dim）
    q = np.asarray([query_vec], dtype="float32")

    # 取多一點結果，再根據 source 過濾
    D, I = obj["index"].search(q, top_k * 3)

    hits = []
    meta = obj["meta"]

    # 根據搜尋結果的索引編號取出 meta
    for idx in I[0]:
        if idx < 0 or idx >= len(meta):
            continue
        m = meta[idx]

        # 如果 sources 有設定，且該段落來源不在 sources 裡 → 跳過
        if sources and m.get("source") not in sources:
            continue

        hits.append(m)
        if len(hits) >= top_k:
            break

    return hits
