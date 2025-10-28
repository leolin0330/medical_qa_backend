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

def embed_paragraphs(paragraph_texts: List[str]) -> List[List[float]]:
    """回傳段落向量；（索引建立流程使用）。"""
    if not paragraph_texts:
        return []
    resp = client.embeddings.create(model=EMBED_MODEL, input=paragraph_texts)
    # 可選：若想記錄嵌入成本就在這裡讀 usage
    # _, _, emb_tt = _tokens(getattr(resp, "usage", None))
    # emb_cost = emb_tt * PRICES[EMBED_MODEL]["in"]
    # print(f"[Embed] tokens={emb_tt} cost=${emb_cost:.6f}")
    return [item.embedding for item in resp.data]

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
    top_k: int = 5,
    mode: str = "auto",
    sources: Optional[List[str]] = None,
    collection_id: str = "_default",   # ✅ 接收 app.py 傳進來的 collectionId
) -> Tuple[str, str, Dict]:
    """
    回傳: (answer, mode_used, meta)
      - mode_used: "general" | "doc"
    """
    mode = (mode or "auto").lower()

    # 1) 強制一般知識
    if mode == "general":
        ans, meta = _answer_general(query)
        return ans, "general", meta

    # 2) 檢查指定 collection 是否已有索引資料
    if not _has_collection_data(collection_id):   # ✅ 改用新的檢查
        ans, meta = _answer_general(query)
        return ans, "general", meta

    # 3) 查詢向量 & 嵌入成本（僅對 query 計算）
    q_embed = client.embeddings.create(model=EMBED_MODEL, input=[query])
    q_vec = q_embed.data[0].embedding
    _, _, emb_tt = _tokens(getattr(q_embed, "usage", None))
    emb_cost = emb_tt * PRICES[EMBED_MODEL]["in"]

    # 4) 相似段落檢索（在「指定的」collection 中）
    top_paras = search_similar_in_collection(collection_id, q_vec, top_k=top_k, sources=sources)  # ✅ 用傳入的 collection_id
    if not top_paras:
        ans, meta = _answer_general(query)
        meta["embedding_cost"] = emb_cost
        meta["total_cost_usd"] = meta.get("total_cost_usd", 0.0) + emb_cost
        return ans, "general", meta

    # 5) 組上下文（過短則切回一般知識）
    ctx_lines, total_chars = [], 0
    for p in top_paras:
        t = (p.get("text") or "")
        if len(t) > 1200:
            t = t[:1200] + "..."
        total_chars += len(t)
        ctx_lines.append(f"第{p.get('page','?')}頁：{t}")

    if mode == "auto" and total_chars < 200:
        ans, meta = _answer_general(query)
        meta["embedding_cost"] = emb_cost
        meta["total_cost_usd"] = meta.get("total_cost_usd", 0.0) + emb_cost
        return ans, "general", meta

    ctx = "\n\n".join(ctx_lines)
    prompt = (
        "你是一位嚴謹的中文醫學AI助手。根據提供的文件內容回答問題，"
        "務必以條列式說明，並在每一點最後以 (第X頁) 標註引用頁碼。"
        "若文件不足以支持答案，請明確說明。\n\n"
        f"【可用文件內容】\n{ctx}\n\n【使用者問題】{query}\n\n請開始回答："
    )

    # 6) Chat 回答 & 成本
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

    # ✅ 將該 collection 的暫存轉錄費結清（而不是 None）
    trans_cost = pop_pending_transcribe_cost(collection_id)

    total_cost = round(emb_cost + chat_cost, 6)

    # sources_meta = []
    # for p in top_paras:
    #     src = p.get("source")
    #     if src:
    #         sources_meta.append({
    #             "text": p.get("text", "")[:100],
    #             "source": src,
    #             "time": p.get("time"),
    #         })

    sources_meta = []
    for p in top_paras:
        src = p.get("source")
        if not src:
            continue
        snippet = (p.get("text") or "").replace("\n", " ")
        sources_meta.append({
            # 兩個鍵都給，前端不管讀 text 還是 snippet 都有
            "snippet": snippet[:160],
            "text":    snippet[:160],

            "source": src,
            "time":   p.get("time"),

            # ✅ 新增：頁碼與相似度
            "page":   p.get("page"),
            "score":  (float(p["score"]) if p.get("score") is not None else None),
        })


    meta = {
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt},
        "embedding_cost": emb_cost,
        "chat_cost": chat_cost,
        "transcribe_cost": trans_cost,
        "total_cost_usd": total_cost + trans_cost,
        "sources": sources_meta,
    }

    # answer_text = chat.choices[0].message.content.strip()
    # return answer_text, "doc", meta


    # 清理 AI 生成內容裡的假頁碼（第1頁）
    PAGE_HINT_RE = re.compile(r'[（(]\s*第\s*\d+\s*頁\s*[)）]')

    answer_text = chat.choices[0].message.content.strip()
    answer_text = PAGE_HINT_RE.sub('', answer_text)  # 移除頁碼標註
    return answer_text, "doc", meta
