# # from typing import List, Dict, Optional
# # import numpy as np
# # import faiss

# # # 全域向量索引與段落儲存
# # index: Optional[faiss.IndexFlatL2] = None
# # embedding_dim: Optional[int] = None
# # paragraphs_list: List[Dict] = []  # 每項: {page:int, text:str}

# # def init_index(dim: int):
# #     global index, embedding_dim
# #     index = faiss.IndexFlatL2(dim)  # L2 距離
# #     embedding_dim = dim

# # def add_embeddings(vectors: List[List[float]], new_paragraphs: List[Dict]):
# #     global index, embedding_dim, paragraphs_list
# #     if not vectors:
# #         return
# #     vec_array = np.array(vectors, dtype="float32")
# #     if index is None:
# #         init_index(vec_array.shape[1])
# #     if embedding_dim != vec_array.shape[1]:
# #         raise ValueError("新向量維度與現有索引不符")
# #     index.add(vec_array)
# #     paragraphs_list.extend(new_paragraphs)

# # def search_similar(query_vector: List[float], k: int = 5) -> List[Dict]:
# #     global index, paragraphs_list
# #     if index is None or index.ntotal == 0:
# #         return []
# #     q = np.array([query_vector], dtype="float32")
# #     distances, indices = index.search(q, k)
# #     results: List[Dict] = []
# #     for idx in indices[0]:
# #         if 0 <= idx < len(paragraphs_list):
# #             results.append(paragraphs_list[idx])
# #     return results

# import os
# import json
# import numpy as np
# import faiss
# from typing import List, Dict, Optional

# INDEX_PATH = "data/index/faiss.index"
# META_PATH = "data/index/metadata.jsonl"

# index: Optional[faiss.IndexFlatL2] = None
# embedding_dim: Optional[int] = None
# paragraphs_list: List[Dict] = []

# def init_index(dim: int):
#     global index, embedding_dim
#     if os.path.exists(INDEX_PATH):
#         index = faiss.read_index(INDEX_PATH)
#         print(f"[向量庫] 已載入 index：{INDEX_PATH}")
#     else:
#         index = faiss.IndexFlatL2(dim)
#         print(f"[向量庫] 新建空 index")
#     embedding_dim = dim

#     # 載入 metadata.jsonl
#     global paragraphs_list
#     if os.path.exists(META_PATH):
#         with open(META_PATH, "r", encoding="utf-8") as f:
#             paragraphs_list = [json.loads(line) for line in f if line.strip()]
#         print(f"[向量庫] 已載入段落資料：{len(paragraphs_list)} 筆")


# def reset_index(dim: int):
#     """完全重建一個新的空索引，並清空 metadata。"""
#     global index, embedding_dim, paragraphs_list
#     import faiss
#     import os

#     index = faiss.IndexFlatL2(dim)
#     embedding_dim = dim
#     paragraphs_list = []  # 清空現有段落資訊

#     os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
#     save_index()


# def save_index():
#     if index:
#         faiss.write_index(index, INDEX_PATH)
#     with open(META_PATH, "w", encoding="utf-8") as f:
#         for p in paragraphs_list:
#             f.write(json.dumps(p, ensure_ascii=False) + "\n")

# def add_embeddings(vectors: List[List[float]], new_paragraphs: List[Dict]):
#     global index, embedding_dim, paragraphs_list
#     if not vectors:
#         return
#     vec_array = np.array(vectors, dtype="float32")
#     if index is None:
#         init_index(vec_array.shape[1])
#     if embedding_dim != vec_array.shape[1]:
#         raise ValueError("新向量維度與現有索引不符")
#     index.add(vec_array)
#     paragraphs_list.extend(new_paragraphs)
#     save_index()

# def search_similar(query_vector: List[float], k: int = 5, sources: Optional[List[str]] = None) -> List[Dict]:
#     global index, paragraphs_list
#     if index is None or index.ntotal == 0:
#         return []
#     q = np.array([query_vector], dtype="float32")
#     distances, indices = index.search(q, k)
#     results: List[Dict] = []
#     for idx in indices[0]:
#         if 0 <= idx < len(paragraphs_list):
#             p = paragraphs_list[idx]
#             if sources and p.get("source") not in sources:
#                 continue
#             results.append(p)
#     return results
# === vector_store.py ===
from __future__ import annotations
import os, json
from pathlib import Path
import faiss
import numpy as np

BASE_DIR = Path("data/collections")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# 以記憶體快取各 collection 的索引與中繼資料
_COLLECTIONS: dict[str, dict] = {}  
# 結構：
# {
#   "myCollection": {
#       "index": faiss.Index,
#       "dim": 3072,
#       "meta": [{"text": "...", "source": "...", "time": ...}, ...],
#   },
#   ...
# }

def _paths(cid: str):
    root = BASE_DIR / cid
    return {
        "root": root,
        "index": root / "index.faiss",
        "meta":  root / "meta.json",
    }

def _load_collection(cid: str):
    p = _paths(cid)
    p["root"].mkdir(parents=True, exist_ok=True)
    meta = []
    if p["meta"].exists():
        try:
            meta = json.loads(p["meta"].read_text(encoding="utf-8"))
        except Exception:
            meta = []
    index = None
    if p["index"].exists():
        index = faiss.read_index(str(p["index"]))
    return index, meta

def _save_collection(cid: str):
    obj = _COLLECTIONS.get(cid)
    if not obj:
        return
    p = _paths(cid)
    p["root"].mkdir(parents=True, exist_ok=True)
    if obj.get("index") is not None:
        faiss.write_index(obj["index"], str(p["index"]))
    p["meta"].write_text(json.dumps(obj.get("meta", []), ensure_ascii=False, indent=2), encoding="utf-8")

def list_collections() -> list[str]:
    return [d.name for d in BASE_DIR.iterdir() if d.is_dir()]

def ensure_collection(cid: str, dim: int | None = None):
    """載入或建立 collection；當沒有 index 且提供 dim 時會新建。"""
    obj = _COLLECTIONS.get(cid)
    if obj:
        return obj
    index, meta = _load_collection(cid)
    if index is None and dim is not None:
        index = faiss.IndexFlatL2(dim)
    if index is None:
        # 尚未建立過索引，先用佔位；等第一次 add_embeddings 時才建
        obj = {"index": None, "dim": dim, "meta": meta}
    else:
        obj = {"index": index, "dim": index.d, "meta": meta}
    _COLLECTIONS[cid] = obj
    return obj

def reset_collection(cid: str, dim: int):
    """清空並重建 collection（覆蓋式）"""
    obj = {"index": faiss.IndexFlatL2(dim), "dim": dim, "meta": []}
    _COLLECTIONS[cid] = obj
    _save_collection(cid)

def init_collection(cid: str, dim: int):
    """累積式使用：若無索引就建，若已有就沿用"""
    obj = ensure_collection(cid, dim)
    if obj["index"] is None:
        obj["index"] = faiss.IndexFlatL2(dim)
        obj["dim"] = dim
        _save_collection(cid)

def add_embeddings(cid: str, vectors: list[list[float]] | np.ndarray, metas: list[dict]):
    obj = ensure_collection(cid)
    if obj["index"] is None:
        # 第一次加入向量時才確定 dim
        dim = len(vectors[0])
        obj["index"] = faiss.IndexFlatL2(dim)
        obj["dim"] = dim
    arr = np.asarray(vectors, dtype="float32")
    if arr.shape[1] != obj["dim"]:
        raise ValueError(f"Dimension mismatch: vec {arr.shape[1]} vs index {obj['dim']}")
    obj["index"].add(arr)
    obj["meta"].extend(metas)
    _save_collection(cid)

def search(cid: str, query_vec: list[float], top_k: int = 5, sources: list[str] | None = None):
    obj = ensure_collection(cid)
    if obj["index"] is None or obj["index"].ntotal == 0:
        return []
    q = np.asarray([query_vec], dtype="float32")
    D, I = obj["index"].search(q, top_k * 3)  # 先抓多一點做過濾
    hits = []
    meta = obj["meta"]
    for idx in I[0]:
        if idx < 0 or idx >= len(meta):
            continue
        m = meta[idx]
        if sources and m.get("source") not in sources:
            continue
        hits.append(m)
        if len(hits) >= top_k:
            break
    return hits
