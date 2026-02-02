from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import List
import httpx
import os
import re
from openai import OpenAI

router = APIRouter()

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

def is_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))

class PaperResult(BaseModel):
    rank: int
    score: int
    title: str
    abstract: str
    journal: str
    journal_score: float
    citations: int
    year: int
    url: str

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5

@router.post("/find_papers", response_model=List[PaperResult])
async def find_papers(payload: QueryRequest = Body(...)):
    try:
        query_text = payload.query

        # Step 0: 如果是中文，就翻成英文再查詢
        if is_chinese(payload.query):
            translation_prompt = f"請將下列醫學查詢翻譯為英文：\n\n{payload.query}"
            translation_resp = openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": translation_prompt}],
                temperature=0.2
            )
            query_text = translation_resp.choices[0].message.content.strip()

        # Step 1: 搜尋 Semantic Scholar
        params = {
            "query": query_text,
            "limit": 10,
            "fields": "title,abstract,year,venue,url,isOpenAccess,citationCount"
        }
        headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY}

        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(SEMANTIC_SCHOLAR_API, params=params, headers=headers)
            response.raise_for_status()
            papers = response.json().get("data", [])

        # Step 2: 對每篇摘要進行 GPT 評分
        summaries = [f"標題：{p['title']}\n摘要：{p.get('abstract', '')}" for p in papers]
        prompt = (
            f"使用者問題：{payload.query}\n\n"
            f"請對以下每篇文章的摘要與使用者問題的相關性打分（0–100 分）。"
            f"輸出格式為：分數｜標題。\n\n"
            + "\n\n".join(summaries)
        )

        gpt_resp = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "你是一位醫學論文推薦引擎，專門幫助使用者找出與他們需求最符合的研究文章。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        gpt_output = gpt_resp.choices[0].message.content

        # Step 3: 解析 GPT 回傳分數
        ranked = []
        for line in gpt_output.strip().split("\n"):
            if "｜" in line:
                score_str, title = line.split("｜", 1)
                try:
                    score = int(score_str.strip())
                    match = next((p for p in papers if p['title'].strip() == title.strip()), None)
                    if match:
                        ranked.append({
                            "score": score,
                            "title": match['title'],
                            "abstract": match.get("abstract", ""),
                            "journal": match.get("venue", ""),
                            "journal_score": 0.0,  # 預留：查 SJR or IF
                            "citations": match.get("citationCount", 0),
                            "year": match.get("year", 0),
                            "url": match.get("url", "")
                        })
                except ValueError:
                    continue

        # Step 4: 排序並補上 rank
        sorted_results = sorted(ranked, key=lambda x: x['score'], reverse=True)[:payload.top_k]
        for i, r in enumerate(sorted_results):
            r['rank'] = i + 1

        return sorted_results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#     {
#   "query": "GLP-1 治療糖尿病",
#   "top_k": 5
# }
