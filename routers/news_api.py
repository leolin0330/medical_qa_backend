# routers/news_api.py

from fastapi import APIRouter, Query, HTTPException
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
import re

router = APIRouter(tags=["News"])

# WHO 最新新聞頁面（不是 RSS）
WHO_NEWS_URL = "https://www.who.int/news"
# https://www.who.int/news


def _parse_title_and_date(raw: str) -> Dict[str, str]:
    """
    把像「7 November 2025News releaseCountries make progress on WHO Pandemic Agreement…」
    這種字串拆成：
      - published: 7 November 2025
      - title: Countries make progress on WHO Pandemic Agreement…
    若無法解析，就全部當作 title。
    """
    text = raw.strip()

    # 1) 嘗試抓開頭的日期（例：7 November 2025）
    date = ""
    m = re.match(r"^(\d{1,2}\s+\w+\s+\d{4})", text)
    if m:
        date = m.group(1).strip()
        text = text[m.end():].strip()

    # 2) 拿掉 News release / Statement / Departmental update 等類型前綴
    leading_labels = [
        "News release",
        "Statement",
        "Feature story",
        "Departmental update",
        "Media advisory",
    ]
    for label in leading_labels:
        if text.startswith(label):
            text = text[len(label):].strip()
            break

    # 3) 有些會變成「Countries make progress...」，就當最後的標題
    # 若 date 解析失敗，就全部塞回 title
    if not text:
        text = raw.strip()

    return {
        "published": date,
        "title": text,
    }


@router.get("/news", summary="取得醫學新聞（WHO）")
def get_news(
    source: str = Query("who", description="來源，目前只支援 'who'"),
    limit: int = Query(10, ge=1, le=50, description="最多幾筆（預設10）"),
) -> Dict[str, List[Dict]]:
    """
    從 WHO Newsroom 頁面抓最新新聞。
    做法：
      - 抓 https://www.who.int/news-room 的 HTML
      - 找出所有 /news/item/... 連結
      - 清理文字，拆出日期與標題
    回傳欄位：
      - title: 乾淨的新聞標題
      - link:  WHO 新聞原文連結
      - published: 解析出的日期（若有）
      - summary: 目前先留空，之後可以再加強
      - source: 'WHO'
    """
    source = source.lower()
    if source != "who":
        return {"items": []}

    # 1) 抓 WHO 新聞頁 HTML
    try:
        resp = requests.get(WHO_NEWS_URL, timeout=10)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"抓取 WHO 新聞頁失敗：{e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"WHO 新聞頁回應狀態碼 {resp.status_code}",
        )

    soup = BeautifulSoup(resp.text, "html.parser")

    items: List[Dict] = []
    seen_links = set()

    # 2) 找頁面中所有 /news/item/xxx 的連結，當作單篇新聞
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/news/item/" not in href:
            continue

        if href in seen_links:
            continue
        seen_links.add(href)

        raw_text = a.get_text(strip=True)
        if not raw_text:
            continue

        parsed = _parse_title_and_date(raw_text)

        # 補成完整網址
        if href.startswith("http"):
            link = href
        else:
            link = f"https://www.who.int{href}"

        items.append({
            "title": parsed["title"],
            "summary": "",               # 之後可以再加：抓內文第一段當摘要
            "link": link,
            "published": parsed["published"],
            "source": "WHO",
        })

        if len(items) >= limit:
            break

    if not items:
        raise HTTPException(
            status_code=502,
            detail="未從 WHO 新聞頁解析出任何新聞，可能是頁面結構改版。"
        )

    return {"items": items}
