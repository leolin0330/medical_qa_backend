# services/qna.py
import os
from typing import List, Tuple, Dict
from openai import OpenAI
from services import vector_store
import json
from pathlib import Path
import re

# === transcribe cost merge ===
import json
from pathlib import Path

COST_STORE = Path("data") / "costs.json"

def search_similar_in_collection(collection_id: str, query_vec: list[float], top_k: int = 5, sources: list[str] | None = None):
    """從指定 collection 檢索相似段落"""
    return vector_store.search(collection_id, query_vec, top_k=top_k, sources=sources)

def _load_costs():
    if COST_STORE.exists():
        try:
            return json.loads(COST_STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_costs(d):
    COST_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def pop_pending_transcribe_cost(collection_id: str | None) -> float:
    """取出並清空待結的轉錄費，避免重覆計算。你目前沒有 collection，就用 _default。"""
    if not collection_id:

        collection_id = "_default"

    d = _load_costs()
    node = d.get(collection_id, {})
    val = float(node.get("pending_transcribe_cost", 0.0) or 0.0)
    if collection_id in d:
        d[collection_id]["pending_transcribe_cost"] = 0.0
        _save_costs(d)
    return round(val, 6)
# === end transcribe cost merge ===


# 初始化 OpenAI 用戶端
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 模型名稱
EMBED_MODEL = "text-embedding-3-large"
CHAT_MODEL  = "gpt-4o"

# --- Pricing (USD) 可由 .env 覆蓋 ---
# 例：PRICE_GPT4O_IN=0.005  PRICE_GPT4O_OUT=0.015  PRICE_EMBED_LARGE_IN=0.13
# 單位：gpt-4o 以「每 1K tokens」；embedding 以「每 1M tokens」
GPT4O_IN_PER_1K   = float(os.getenv("PRICE_GPT4O_IN",  "0.005"))
GPT4O_OUT_PER_1K  = float(os.getenv("PRICE_GPT4O_OUT", "0.015"))
EMB_LARGE_PER_1M  = float(os.getenv("PRICE_EMBED_LARGE_IN", "0.13"))

# 轉為「每 1 token」單價
PRICES = {
    "gpt-4o": {
        "in":  GPT4O_IN_PER_1K  / 1000.0,      # 輸入 每 token
        "out": GPT4O_OUT_PER_1K / 1000.0,      # 輸出 每 token
    },
    "text-embedding-3-large": {
        "in": EMB_LARGE_PER_1M / 1_000_000.0,  # 嵌入 每 token
    },
}

def _tokens(u) -> Tuple[int, int, int]:
    """把 OpenAI SDK 的 usage 物件安全轉成 (prompt, completion, total)。"""
    try:
        pt = getattr(u, "prompt_tokens", 0) or 0
        ct = getattr(u, "completion_tokens", 0) or 0
        tt = getattr(u, "total_tokens", 0) or (pt + ct)
        return int(pt), int(ct), int(tt)
    except Exception:
        return 0, 0, 0

# def _has_index() -> bool:
#     try:
#         return (
#             vector_store.index is not None
#             and vector_store.index.ntotal > 0
#             and len(vector_store.paragraphs_list) > 0
#         )
#     except Exception:
#         return False

def _has_collection_data(cid: str) -> bool:
    try:
        obj = vector_store.ensure_collection(cid)
        return (obj.get("index") is not None
                and obj["index"].ntotal > 0
                and len(obj.get("meta", [])) > 0)
    except Exception:
        return False

def embed_paragraphs(paragraph_texts: list[str]) -> list[list[float]]:
    all_vectors = []
    batch, batch_tokens = [], 0
    for txt in paragraph_texts:
        t = len(txt) // 3.5  # 粗估 token
        if batch_tokens + t > 7000:
            resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
            all_vectors.extend([d.embedding for d in resp.data])
            batch, batch_tokens = [], 0
        batch.append(txt)
        batch_tokens += t
    if batch:
        resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
        all_vectors.extend([d.embedding for d in resp.data])
    return all_vectors


def _answer_general(query: str) -> Tuple[str, Dict]:
    """一般知識回答 + 成本"""
    chat = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是專業且謹慎的中文醫學知識助手。"
                    "當沒有可靠文件內容時，以一般醫學常識回覆；"
                    "請條列重點、常見症狀、風險與就醫時機，避免個別診斷。"
                ),
            },
            {
                "role": "user",
                "content": f"問題：{query}\n\n請條列重點並提醒何時應就醫。",
            },
        ],
        temperature=0,
    )
    pt, ct, tt = _tokens(getattr(chat, "usage", None))
    cost = pt * PRICES[CHAT_MODEL]["in"] + ct * PRICES[CHAT_MODEL]["out"]
    return chat.choices[0].message.content.strip(), {
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt},
        "chat_cost": cost,
        "total_cost_usd": cost,
    }

from typing import Optional, List
from typing import Optional, List, Tuple, Dict


def answer_question(
    query: str,
    mode: str ,
    top_k: int = 5,
    sources: Optional[List[str]] = None,
    collection_id: Optional[str] = None,  # ← 改成可為 None，不要給預設 "_default"
) -> Tuple[str, str, Dict]:
    """
    回傳: (answer, mode_used, meta)
      - mode_used: "general" | "doc"
    """
    mode = mode.lower()
    CONF_THRESHOLD = 0.25  # 檢索信心門檻（可調 0.2~0.35）

    # ---- 共用的小函式 ----
    def _meta_zero(**extra):
        base = {
            "usage": {},
            "embedding_cost": 0.0,
            "chat_cost": 0.0,
            "transcribe_cost": 0.0,
            "total_cost_usd": 0.0,
            "sources": [],
        }
        base.update(extra)
        return base

    # 1) 強制一般知識：完全不看文件、也不做 embedding
    if mode == "general":
        ans, meta = _answer_general(query)  # 你原本的純聊天函式
        # 確保成本鍵存在
        meta.setdefault("embedding_cost", 0.0)
        meta.setdefault("transcribe_cost", 0.0)
        meta.setdefault("total_cost_usd", meta.get("chat_cost", 0.0))
        return ans, "general", meta

    # 2) 是否可用文件？
    use_docs = False
    if (sources and len(sources) > 0) or (collection_id and len(collection_id) > 0):
        # 只有在指定了來源/collection_id 且真的「有索引資料」時才視為可用
        if collection_id and not _has_collection_data(collection_id):
            use_docs = False
        else:
            # 若你允許只靠 sources 搜，也可標 True；若一定要 collection，則依需求調整
            use_docs = True

    # 若不可用文件且不是 doc 模式 → 直接一般知識
    if not use_docs and mode != "doc":
        ans, meta = _answer_general(query)
        meta.setdefault("embedding_cost", 0.0)
        meta.setdefault("transcribe_cost", 0.0)
        meta.setdefault("total_cost_usd", meta.get("chat_cost", 0.0))
        return ans, "general", meta

    # 3) 如果是 doc 模式但不可用文件 → 明確回覆找不到（或丟 400 由上層處理）
    if mode == "doc" and not use_docs:
        # 你也可以選擇 raise HTTPException(400, ...) 交給 /ask 擋
        ans = "根據目前指定的文件/知識庫，無法進行檢索，請先上傳或選擇正確的來源。"
        return ans, "doc", _meta_zero()

    # 走到這裡：代表「文件可用」（auto 或 doc）
    emb_cost = 0.0
    trans_cost = 0.0

    # 4) 僅在使用文件時才做 query embedding（否則會多算錢）
    q_embed = client.embeddings.create(model=EMBED_MODEL, input=[query])
    q_vec = q_embed.data[0].embedding
    _, _, emb_tt = _tokens(getattr(q_embed, "usage", None))
    emb_cost = emb_tt * PRICES[EMBED_MODEL]["in"]

    # 5) 相似段落檢索（在指定 collection/sources 中）
    top_paras = search_similar_in_collection(
        collection_id,
        q_vec,
        top_k=top_k,
        sources=sources,
    ) or []

    # 6) 自動模式門檻：無檢索結果或分數過低 → 轉一般知識
    top_score = float(top_paras[0].get("score", 0.0)) if top_paras else 0.0
    # if mode == "auto" and (not top_paras or top_score < CONF_THRESHOLD):
    #     ans, meta = _answer_general(query)
    #     # 把剛才已經花掉的 embedding 成本加回去
    #     meta["embedding_cost"] = meta.get("embedding_cost", 0.0) + emb_cost
    #     meta["total_cost_usd"] = meta.get("total_cost_usd", 0.0) + emb_cost
    #     meta.setdefault("transcribe_cost", 0.0)
    #     return ans, "general", meta

    # 7) 組上下文（檢查太短情況；auto 可再保險一次）
    ctx_lines, total_chars = [], 0
    for p in top_paras:
        t = (p.get("text") or "")
        if len(t) > 1200:
            t = t[:1200] + "..."
        total_chars += len(t)
        page = p.get("page", "?")
        ctx_lines.append(f"第{page}頁：{t}")

    # if mode == "auto" and total_chars < 200:
    #     ans, meta = _answer_general(query)
    #     meta["embedding_cost"] = meta.get("embedding_cost", 0.0) + emb_cost
    #     meta["total_cost_usd"] = meta.get("total_cost_usd", 0.0) + emb_cost
    #     meta.setdefault("transcribe_cost", 0.0)
    #     return ans, "general", meta

    ctx = "\n\n".join(ctx_lines)

    # 8) 只有在文件模式（doc 或 auto 經過門檻保留文件）時，才用「根據文件內容」的語氣
    prompt = (
        "你是一位嚴謹的中文醫學AI助手。請僅根據下面提供的文件內容回答問題，"
        "務必以條列式說明，並在每一點最後以 (第X頁) 標註引用頁碼。"
        "若文件不足以支持答案，請明確說明。\n\n"
        f"【可用文件內容】\n{ctx}\n\n【使用者問題】{query}\n\n請開始回答："
    )

    chat = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "你是專業且謹慎的醫學知識助手，回答時務必標註引用頁碼。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    pt, ct, tt = _tokens(getattr(chat, "usage", None))
    chat_cost = round(pt * PRICES[CHAT_MODEL]["in"] + ct * PRICES[CHAT_MODEL]["out"], 6)

    # 若你有記錄該 collection 的暫存轉錄費，只在走文件路時結清
    trans_cost = pop_pending_transcribe_cost(collection_id) if collection_id else 0.0

    total_cost = round(emb_cost + chat_cost, 6)

    # sources_meta（來源清單）
    sources_meta = []
    for p in top_paras:
        src = p.get("source")
        if not src:
            continue
        snippet = (p.get("text") or "").replace("\n", " ")
        sources_meta.append({
            "snippet": snippet[:160],
            "text":    snippet[:160],
            "source":  src,
            "time":    p.get("time"),
            "page":    p.get("page"),
            "score":   (float(p["score"]) if p.get("score") is not None else None),
        })

    # 清理 AI 生成內容裡的假頁碼（第1頁）
    PAGE_HINT_RE = re.compile(r'[（(]\s*第\s*\d+\s*頁\s*[)）]')
    answer_text = chat.choices[0].message.content.strip()
    answer_text = PAGE_HINT_RE.sub('', answer_text)

    meta = {
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt},
        "embedding_cost": emb_cost,
        "chat_cost": chat_cost,
        "transcribe_cost": trans_cost,
        "total_cost_usd": total_cost + trans_cost,
        "sources": sources_meta,
        "collection_id": collection_id,
    }
    return answer_text, "doc", meta

