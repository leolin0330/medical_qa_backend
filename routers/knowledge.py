# routers/knowledge.py
from fastapi import APIRouter, Query

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# 先用假資料，之後會換成爬下來的內容
_ITEMS = [
    {
        "id": "cond_asthma_v1",
        "title": "氣喘（Asthma）",
        "summary": "慢性發炎性氣道疾病，症狀含喘鳴、夜咳。",
        "body_md": "### 定義\n氣喘是氣道慢性發炎…\n\n### 何時就醫\n呼吸困難、嘴唇發紫請立即就醫。\n",
        "last_reviewed": "2025-07-20",
        "source": "示範資料",
        "locale": "zh-TW",
    },
    {
        "id": "cond_fever_child",
        "title": "兒童發燒居家處置",
        "summary": "量體溫、補充水分、觀察活動力與警訊。",
        "body_md": "### 量測\n腋溫≥38℃ 定義為發燒…\n\n### 就醫警語\n3個月以下嬰兒發燒、意識不清、抽搐，立即就醫。\n",
        "last_reviewed": "2025-06-10",
        "source": "示範資料",
        "locale": "zh-TW",
    },
]

@router.get("/search")
def search(q: str = Query("", description="關鍵字（可留空）"), limit: int = 50):
    if not q:
        return {"items": _ITEMS[:min(limit, len(_ITEMS))]}
    q = q.strip()
    hits = [it for it in _ITEMS if q in it["title"] or q in it["summary"] or q in it["body_md"]]
    return {"items": hits[:min(limit, len(hits))]}

@router.get("/item/{kid}")
def get_item(kid: str):
    for it in _ITEMS:
        if it["id"] == kid:
            return it
    return {"error": "not_found"}
