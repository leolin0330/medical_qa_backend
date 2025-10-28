# Medical QA Backend (FastAPI + OpenAI + FAISS)

這是一個最小可用 (MVP) 的醫學問答後端：
- 上傳 PDF → 解析文字 → 切段 → 嵌入至 FAISS 向量庫
- 以問題做檢索 → 讓 GPT 生成含頁碼引用的答案

## 快速開始 (Windows + VS Code)

1) 將 `.env.example` 改名為 `.env`，並把你的 `OPENAI_API_KEY` 貼上去。
2) 安裝套件：
   ```bash
   pip install -r requirements.txt
   ```
3) 啟動：
   ```bash
   uvicorn app:app --reload
   ```
4) 打開互動文件： http://127.0.0.1:8000/docs

### 測試流程
- 用 `/upload` 上傳 PDF（Content-Type: multipart/form-data）
- 用 `/ask` 送出表單欄位 `query`（可選 `top_k`）

### 常見問題
- **faiss-cpu 安裝**：若遇到安裝問題，可先升級 pip 或使用 Conda 安裝。
- **長文件**：如 PDF 很長，請分批上傳或在 `pdf_utils.py` 中調整分段策略。
- **保護個資**：上傳前請先完成去識別化。此專案僅作教育/內部研究用途，非臨床醫囑。

### 下一步
- 持久化 FAISS 索引
- 改用 pgvector / Qdrant
- 新增 Docx、圖片 OCR、權限與稽核
