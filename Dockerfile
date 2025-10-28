# 1) 精簡基底
FROM python:3.11-slim

# 2) 系統相依（給影片/音訊/FAISS/OCR 用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    libgomp1 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# 3) 工作目錄與環境
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# 4) 安裝 Python 套件（先複製 requirements.txt 利用快取）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5) 複製程式碼
COPY . .

# 6) 用 Cloud Run 的 $PORT（預設 8080）
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "${PORT:-8080}"]
