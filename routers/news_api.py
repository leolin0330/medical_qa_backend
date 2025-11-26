


# routers/news_api.py

from fastapi import APIRouter, Query, HTTPException
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import os
import time
from datetime import datetime

# =============== 基本設定 ===============
router = APIRouter(tags=["News"])

# 快取：每天更新一次
_news_cache: Dict[str, Dict] = {}

WHO_NEWS_URL = "https://www.who.int/news"
WHO_HEADLINES_URL = "https://www.who.int/news-room/headlines"
HEADERS = {"User-Agent": "Mozilla/5.0 (Medical-QA/1.0)"}

# =============== 翻譯設定（OpenAI） ===============
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("NEWS_TRANSLATE_MODEL", "gpt-4o-mini")
# 簡單的快取，避免重複同句翻譯重花錢
_translation_cache: Dict[tuple, str] = {}  # key=(text, target) -> translated

def _translate_text(text: str, target: str = "zh-TW") -> str:
    """用 OpenAI 將英文翻成目標語言；失敗則回空字串（不中斷主流程）。"""
    if not text or not OPENAI_API_KEY:
        return ""

    key = (text.strip(), target)
    if key in _translation_cache:
        return _translation_cache[key]

    try:
        # OpenAI v1 SDK
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = (
            f"請將以下英文翻譯成{target}，保持專有名詞與醫學用語準確，"
            "不要添加額外解釋或括號註解，只輸出譯文：\n\n" + text.strip()
        )
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        out = (resp.choices[0].message.content or "").strip()
        # 最後做個很小心的清洗
        out = out.replace("\u200b", "").strip()
        _translation_cache[key] = out
        # 輕微節流，避免速率過快（可視需要調整/移除）
        time.sleep(0.1)
        return out
    except Exception:
        return ""

# =============== 快訊快取（只針對 WHO + 中文） ===============
# ★ 新增：整天共用一份「WHO 快訊（已翻成中文）」快取，避免每次都重抓＋重翻
_NEWS_CACHE: Dict[str, Any] = {}      # 存今天的完整資料：date / target_lang / items
_NEWS_CACHE_DATE: str | None = None   # 紀錄這份快取是「哪一天」產生的


def refresh_who_news(limit: int = 20, target_lang: str = "zh-TW") -> Dict[str, Any]:
    """
    ★ 新增：預抓 WHO 快訊 + 翻譯，並寫進全域快取。
    - 之後 /news 或 /news/list 就可以直接用這份資料，而不是每次都重抓。
    - 這個函式可以在：
        1) 伺服器啟動時呼叫（@app.on_event("startup")）
        2) 之後要做排程（每天抓一次）也會用到
    """
    global _NEWS_CACHE, _NEWS_CACHE_DATE

    today = datetime.now().strftime("%Y-%m-%d")

    # 直接呼叫你原本的邏輯：抓最新 WHO 新聞並作翻譯
    # 注意：這裡強制 do_translate=True，因為你的 user 只看中文
    items = _fetch_latest_who_news(
        limit=limit,
        do_translate=True,
        target=target_lang,
    )

    # 把結果塞進快取
    _NEWS_CACHE = {
        "date": today,
        "target_lang": target_lang,
        "items": items,   # items 裡面每一筆都有 title/title_zh/summary_zh 等欄位
    }
    _NEWS_CACHE_DATE = today

    print(f"[NEWS] WHO 快訊已預抓完成，共 {len(items)} 筆，語言={target_lang}")
    return _NEWS_CACHE


def get_today_who_news(limit: int = 20, target_lang: str = "zh-TW") -> Dict[str, Any]:
    """
    ★ 新增：對外提供一個「安全拿快取」的函式。
    - 如果今天還沒抓過 → 自動呼叫 refresh_who_news()
    - 如果已經有今天的快取 → 直接用快取，最多回傳 limit 筆
    - 之後 /news API 就可以改成呼叫這個，而不是每次重抓。
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # 如果日期不同（跨天）或沒快取，就重抓一次
    if _NEWS_CACHE_DATE != today:
        refresh_who_news(limit=limit, target_lang=target_lang)

    # 做一份淺拷貝，避免外部亂改原始快取
    data = dict(_NEWS_CACHE)
    # 只回前 limit 筆，避免前端要得比較少
    data["items"] = (_NEWS_CACHE.get("items") or [])[:limit]
    return data



# =============== 抓頁面 ===============
def _safe_get(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=12, headers=HEADERS)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

# /news 卡片
def _parse_news_cards(limit: int) -> List[Dict[str, Any]]:
    soup = _safe_get(WHO_NEWS_URL)
    cards = soup.select("div.sf-publications-item")
    out: List[Dict[str, Any]] = []
    for card in cards:
        if len(out) >= limit:
            break
        title_tag = card.find("h3", class_="sf-publications-item__title")
        if not title_tag:
            continue
        link_tag = card.find("a", class_="page-url") or title_tag.find_parent("a")
        if not link_tag or not link_tag.get("href"):
            continue
        url = urljoin(WHO_NEWS_URL, link_tag["href"])
        title = title_tag.get_text(strip=True)
        date_div = card.find("div", class_="sf-publications-item__date")
        published = date_div.get_text(strip=True) if date_div else ""
        out.append({
            "title": title,
            "url": url,
            "published": published,
            "summary": "",
            "image": "",
            "source": "WHO",
        })
    return out

# /news-room/headlines 最新
def _parse_headlines(limit: int) -> List[Dict[str, Any]]:
    soup = _safe_get(WHO_HEADLINES_URL)
    items: List[Dict[str, Any]] = []
    seen = set()
    date_re = re.compile(r"\d{1,2}\s+\w+\s+\d{4}")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/news/item/" not in href:
            continue
        url = urljoin(WHO_HEADLINES_URL, href)
        if url in seen:
            continue
        text = a.get_text(strip=True)
        m = date_re.search(text)
        if not m:
            continue
        published = m.group(0)
        title = text[m.end():].strip()
        items.append({
            "title": title,
            "url": url,
            "published": published,
            "summary": "",
            "image": "",
            "source": "WHO",
        })
        seen.add(url)
        if len(items) >= limit:
            break
    return items

def _enrich_with_detail(item: Dict[str, Any], *, do_translate: bool, target: str) -> None:
    """進入 /news/item/... 內頁補 title/summary/image；必要時翻譯成 target。"""
    url = item["url"]
    try:
        soup = _safe_get(url)
    except Exception:
        # 內頁掛了就跳過，不要讓整體 API 爆
        return

    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            item["title"] = t

    # 內頁補日期
    if not item.get("published"):
        date_re = re.compile(r"\d{1,2}\s+\w+\s+\d{4}")
        m = date_re.search(soup.get_text(" ", strip=True))
        if m:
            item["published"] = m.group(0)

    # 摘要：h1 後第一個 <p>，找不到就全頁第一個 <p>
    summary = ""
    if h1:
        for sib in h1.next_siblings:
            if getattr(sib, "name", None) == "p":
                summary = sib.get_text(strip=True)
                if summary:
                    break
    if not summary:
        p = soup.find("p")
        summary = p.get_text(strip=True) if p else ""
    if summary:
        item["summary"] = summary

    # 圖片：第一張 <img>
    img = soup.find("img")
    if img and img.get("src"):
        item["image"] = urljoin(url, img["src"])

    # ===== 在這裡做翻譯（選用）=====
    if do_translate:
        # 只翻有內容的欄位；翻譯失敗就留空，不影響英文
        zh_title = _translate_text(item.get("title", ""), target)
        zh_summary = _translate_text(item.get("summary", ""), target)
        if zh_title:
            item["title_zh"] = zh_title
        if zh_summary:
            item["summary_zh"] = zh_summary

def _fetch_latest_who_news(limit: int = 10, *, do_translate: bool, target: str) -> List[Dict[str, Any]]:
    """先抓 /news 卡片 → 再抓 headlines → 合併去重 → 取前 limit → 內頁補欄位（含可選翻譯）。"""
    combined: List[Dict[str, Any]] = []
    seen = set()

    # 1) /news 卡片優先
    for it in _parse_news_cards(limit):
        if it["url"] in seen:
            continue
        combined.append(it); seen.add(it["url"])
        if len(combined) >= limit:
            break

    # 2) 補 headlines
    if len(combined) < limit:
        for it in _parse_headlines(limit):
            if it["url"] in seen:
                continue
            combined.append(it); seen.add(it["url"])
            if len(combined) >= limit:
                break

    if not combined:
        raise HTTPException(status_code=502, detail="WHO 頁面可能改版，解析不到任何新聞")

    # 3) 內頁補 summary/image 以及可選翻譯
    for it in combined:
        try:
            _enrich_with_detail(it, do_translate=do_translate, target=target)
        except Exception:
            continue

    return combined[:limit]

# =============== 對外路由 ===============
@router.get("/news", summary="取得今日快取的 WHO 新聞（秒開版）")
def api_get_news(
    limit: int = Query(10, ge=1, le=50, description="最多幾筆（1~50）"),
    lang: str = Query("zh-TW", description="語言（預設繁中）")
):
    """
    使用 get_today_who_news()，避免每次都重新抓 WHO。
    回傳只有：標題、摘要、日期、圖片（不含全文）
    """
    data = get_today_who_news(limit=limit, target_lang=lang)

    items = []
    for it in data["items"]:
        items.append({
            "title": it.get("title_zh") or it.get("title", ""),
            "summary": it.get("summary_zh") or it.get("summary", ""),
            "published": it.get("published", ""),
            "image": it.get("image", ""),
            "url": it.get("url", ""),  # 讓前端之後能看全文
        })

    return {
        "date": data["date"],
        "count": len(items),
        "items": items,
        "note": "使用今日快取（不會重新抓 WHO）"
    }

# @router.get("/news", summary="取得 WHO 最新新聞（/news 卡片 + Headlines 合併，可選繁中翻譯）")
# def get_news(
#     source: str = Query("who", description="目前只支援 'who'"),
#     limit: int = Query(10, ge=1, le=10, description="最多幾筆（1~10）"),
#     lang: str = Query("en", description="目標語言（ex: en, zh-TW, zh, zh-Hant）"),
#     translate: bool = Query(False, description="是否啟用伺服器端翻譯"),
#     target: str = Query(None, description="覆蓋目標語言；預設跟 lang 同"),
# ):
#     """
#     例：
#       /news?source=who&limit=10                 -> 英文
#       /news?source=who&limit=10&lang=zh-TW      -> 觸發繁中（等同 translate=true）
#       /news?translate=true&target=zh-TW         -> 強制翻譯到指定語言
#     回傳資料包含：
#       英文欄位：title, summary
#       若翻譯成功：title_zh, summary_zh（或 target 語言對應欄位名固定為 *_zh）
#     """
#     if source.lower() != "who":
#         raise HTTPException(status_code=400, detail="目前只支援 source=who")

#     # 判斷是否要翻譯 & 目標語言
#     do_translate = translate or lang.lower() in ("zh", "zh-tw", "zh-hant")
#     target_lang = (target or (lang if do_translate else "en")).strip() or "zh-TW"

#     items = _fetch_latest_who_news(limit=limit, do_translate=do_translate, target=target_lang)

#     return {
#         "items": items,
#         "translated": bool(do_translate and OPENAI_API_KEY),
#         "target_lang": target_lang if do_translate else "en",
#         "note": (
#             None if OPENAI_API_KEY else
#             "OPENAI_API_KEY 未設定，已回傳英文原文"
#         )
#     }
