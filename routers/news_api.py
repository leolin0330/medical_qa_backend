# routers/news_api.py

from fastapi import APIRouter, Query, HTTPException
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

router = APIRouter(tags=["News"])


# WHO 頭條頁（你截圖看到那串列表實際上來自這裡）
# WHO_HEADLINES_URL = "https://www.who.int/news-room/headlines"
# WHO_NEWS_URL = "https://www.who.int/news"
# HEADERS = {"User-Agent": "Mozilla/5.0 (Medical-QA/1.0)"}


# def _safe_get(url: str) -> BeautifulSoup:
#     try:
#         resp = requests.get(url, timeout=10, headers=HEADERS)
#         resp.raise_for_status()
#     except Exception as e:
#         raise HTTPException(status_code=502, detail=f"抓取 {url} 失敗：{e}")
#     return BeautifulSoup(resp.text, "html.parser")


# def _parse_headlines(limit: int) -> List[Dict[str, Any]]:
#     """
#     從 Headlines 頁面抓出最新幾則新聞（只含 date / title / url）。
#     頁面結構大概是：

#       ## Latest
#       <a href="/news/item/...">
#         11 November 2025 Statement Statement of the Forty-third meeting of ...
#       </a>

#     我們用 /news/item/ 當篩選條件。
#     """
#     soup = _safe_get(WHO_HEADLINES_URL)
#     items: List[Dict[str, Any]] = []
#     seen_links = set()

#     date_re = re.compile(r"\d{1,2}\s+\w+\s+\d{4}")

#     for a in soup.find_all("a", href=True):
#         href = a["href"]
#         if "/news/item/" not in href:
#             continue

#         url = urljoin(WHO_HEADLINES_URL, href)
#         if url in seen_links:
#             continue

#         text = a.get_text(strip=True)
#         if not text:
#             continue

#         # 先把日期拆出來
#         m = date_re.search(text)
#         if not m:
#             continue
#         published = m.group(0)
#         rest = text[m.end():].strip()

#         # rest 大概像： "News release Countries make progress on ..."
#         # 這裡簡單處理：當作完整標題，前面的 "News release" 保留，其實也挺清楚
#         title = rest

#         items.append(
#             {
#                 "title": title,
#                 "url": url,
#                 "published": published,
#                 # 先占位，等會去內頁補 summary / image
#                 "summary": "",
#                 "image": "",
#                 "source": "WHO",
#             }
#         )
#         seen_links.add(url)

#         if len(items) >= limit:
#             break

#     if not items:
#         raise HTTPException(
#             status_code=502,
#             detail="未從 WHO Headlines 頁解析出任何新聞，可能是頁面結構改版。"
#         )

#     return items


# def _enrich_with_detail(item: Dict[str, Any]) -> None:
#     """
#     進各別的 /news/item/... 頁面，補 summary（第一段內文）和 image（第一張圖）。
#     失敗就跳過，不要讓整體爆掉。
#     """
#     url = item["url"]
#     try:
#         soup = _safe_get(url)
#     except HTTPException:
#         return

#     # 標題跟日期以內頁為準（有時候 Headlines 文字會比較長或被截）
#     h1 = soup.find("h1")
#     if h1:
#         title = h1.get_text(strip=True)
#         if title:
#             item["title"] = title

#     # 內頁日期：通常在 h1 下方的單獨一行
#     date_re = re.compile(r"\d{1,2}\s+\w+\s+\d{4}")
#     if not item.get("published"):
#         text = soup.get_text(" ", strip=True)
#         m = date_re.search(text)
#         if m:
#             item["published"] = m.group(0)

#     # 摘要：取 h1 之後遇到的第一個 <p>
#     summary = ""
#     if h1:
#         for sib in h1.next_siblings:
#             if getattr(sib, "name", None) == "p":
#                 summary = sib.get_text(strip=True)
#                 if summary:
#                     break
#     if not summary:
#         p = soup.find("p")
#         summary = p.get_text(strip=True) if p else ""
#     if summary:
#         item["summary"] = summary

#     # 圖片：簡單抓第一張 <img>
#     img = soup.find("img")
#     if img and img.get("src"):
#         item["image"] = urljoin(url, img["src"])


# def _fetch_latest_who_news(limit: int = 10) -> List[Dict[str, Any]]:
#     # 先從 Headlines 抓出前 limit 則
#     items = _parse_headlines(limit=limit)

#     # 再逐條去內頁補 summary / image（盡力而為，失敗就保持原樣）
#     for item in items:
#         try:
#             _enrich_with_detail(item)
#         except Exception:
#             continue

#     return items


# @router.get("/news", summary="取得 WHO 最新新聞（Headlines + 內頁補充）")
# def get_news(
#     source: str = Query("who", description="目前只支援 'who'"),
#     limit: int = Query(10, ge=1, le=10, description="最多幾筆（1~10）"),
# ):
#     """
#     GET /news?source=who&limit=10

#     回傳：
#     {
#       "items": [
#         {
#           "title": "...",
#           "url": "...",
#           "published": "11 November 2025",
#           "summary": "...",
#           "image": "https://...",
#           "source": "WHO"
#         },
#         ...
#       ]
#     }
#     """
#     if source.lower() != "who":
#         raise HTTPException(status_code=400, detail="目前只支援 source=who")

#     items = _fetch_latest_who_news(limit=limit)
#     return {"items": items}


WHO_NEWS_URL = "https://www.who.int/news"
WHO_HEADLINES_URL = "https://www.who.int/news-room/headlines"
HEADERS = {"User-Agent": "Mozilla/5.0 (Medical-QA/1.0)"}

def _safe_get(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=12, headers=HEADERS)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def _parse_news_cards(limit: int) -> List[Dict[str, Any]]:
    """
    從 https://www.who.int/news 抓卡片區（就是你截圖那一區）。
    取出：title / url / published。summary/image 之後內頁補。
    """
    soup = _safe_get(WHO_NEWS_URL)
    cards = soup.select("div.sf-publications-item")
    out: List[Dict[str, Any]] = []
    for card in cards:
        if len(out) >= limit:
            break

        title_tag = card.find("h3", class_="sf-publications-item__title")
        if not title_tag:
            continue
        # 連結：先找 class=page-url，否則找包 title 的父 <a>
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

def _parse_headlines(limit: int) -> List[Dict[str, Any]]:
    """
    從 https://www.who.int/news-room/headlines 抓 Latest 區塊連結（/news/item/...）。
    """
    soup = _safe_get(WHO_HEADLINES_URL)
    items: List[Dict[str, Any]] = []
    seen = set()
    date_re = re.compile(r"\d{1,2}\s+\w+\s+\d{4}")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 只要新聞詳情頁（/news/item/）
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
        title = text[m.end():].strip()  # 日期後面的整段當標題（內頁再校正）
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

def _enrich_with_detail(item: Dict[str, Any]) -> None:
    """
    進 /news/item/... 內頁補 title/summary/image（有些是 campaign/其他路徑也盡量抓）。
    """
    url = item["url"]
    try:
        soup = _safe_get(url)
    except Exception:
        return

    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            item["title"] = t

    # 日期盡量從頁面文字補；若已有就不動
    if not item.get("published"):
        date_re = re.compile(r"\d{1,2}\s+\w+\s+\d{4}")
        m = date_re.search(soup.get_text(" ", strip=True))
        if m:
            item["published"] = m.group(0)

    # 摘要：h1 之後遇到的第一個 <p>
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

def _fetch_latest_who_news(limit: int = 10) -> List[Dict[str, Any]]:
    """
    先抓 /news 卡片（你要的那區）→ 再抓 headlines → 合併去重 → 取前 limit。
    """
    combined: List[Dict[str, Any]] = []
    seen = set()

    # 1) /news 卡片優先（避免你想看的被 headlines 覆蓋）
    for it in _parse_news_cards(limit):
        if it["url"] in seen:
            continue
        combined.append(it); seen.add(it["url"])
        if len(combined) >= limit:
            break

    # 2) 不夠就補 headlines
    if len(combined) < limit:
        for it in _parse_headlines(limit):
            if it["url"] in seen:
                continue
            combined.append(it); seen.add(it["url"])
            if len(combined) >= limit:
                break

    if not combined:
        raise HTTPException(status_code=502, detail="WHO 頁面可能改版，解析不到任何新聞")

    # 3) 盡力補 summary/image
    for it in combined:
        try:
            _enrich_with_detail(it)
        except Exception:
            continue

    return combined[:limit]

@router.get("/news", summary="取得 WHO 最新新聞（/news 卡片 + Headlines 合併）")
def get_news(
    source: str = Query("who", description="目前只支援 'who'"),
    limit: int = Query(10, ge=1, le=10, description="最多幾筆（1~10）"),
):
    if source.lower() != "who":
        raise HTTPException(status_code=400, detail="目前只支援 source=who")

    items = _fetch_latest_who_news(limit=limit)
    return {"items": items}
