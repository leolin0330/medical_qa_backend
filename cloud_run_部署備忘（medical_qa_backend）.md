# Cloud Run 部署備忘（medical-qa-backend）

> 目的：避免之後忘記 **如何重新部署 / 關閉 / 設定金鑰**，這份文件照著做即可。

---

## 一、整體架構快速回顧

- **前端**：Flutter App（Android 手機）
- **後端**：FastAPI + Uvicorn
- **部署平台**：Google Cloud Run
- **映像來源**：GitHub → Cloud Build → Artifact Registry

---

## 二、部署前檢查清單（本地端）

### 1️⃣ 專案必備檔案

- `Dockerfile`
- `requirements.txt`
- `app.py`（FastAPI app）

### 2️⃣ FastAPI 啟動方式（很重要）

**一定要聽 Cloud Run 的 PORT（8080）**

```python
import os

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
```

---

## 三、Dockerfile 標準範本（可直接用）

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 四、第一次部署 Cloud Run（GUI 流程）

1. 進入 **GCP Console → Cloud Run**
2. 點「建立服務」
3. 選擇：
   - 來源：**從原始碼（Cloud Build）**
   - Repository：你的 GitHub repo
4. 區域：`asia-east1`
5. 允許未經驗證存取（前端 App 才連得到）

---

## 五、⚠️ 關鍵步驟：設定「變數與密鑰」（一定要做）

### 為什麼？

你的後端有這行：

```python
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

**Cloud Run 不會自動有這個變數，一定要手動設**

---

### 設定 OpenAI API Key（GUI）

1. Cloud Run → 你的服務
2. 點「**編輯並部署新的修訂版本**」
3. 切到「**變數與密鑰**」
4. 新增環境變數：

| 名稱 | 值 |
|----|----|
| `OPENAI_API_KEY` | `sk-xxxxxxx` |

5. 儲存並部署

✅ 沒設這一步一定會出現：

```
openai.OpenAIError: The api_key client option must be set
```

---

## 六、確認部署是否成功

### 1️⃣ Cloud Run Logs

```bash
gcloud run services logs read medical-qa-backend \
  --region=asia-east1 \
  --project=medical-app-476502
```

看到以下代表成功：

```
Uvicorn running on http://0.0.0.0:8080
```

### 2️⃣ 瀏覽器測試

```text
https://medical-qa-backend-xxxx.asia-east1.run.app/docs
```

能看到 Swagger UI 即正常

---

## 七、Flutter App 連線設定注意事項

### API Base URL（正式）

```dart
const String baseUrl = "https://medical-qa-backend-xxxx.asia-east1.run.app";
```

⚠️ **不要再用**：
- `192.168.x.x`
- `localhost`

（真實手機一定連不到）

---

## 八、如何「關掉 Cloud Run 避免花錢」

### 方法一（最乾淨，推薦）✅

**直接刪除服務**

Cloud Run → 服務 → 右上角「刪除」

- 不會再產生費用
- 之後要用再重新部署即可

---

### 方法二（保留但幾乎不跑）⚠️

- 最小執行個體數：`0`
- 不主動打 API

⚠️ 仍可能有極少量費用（不建議）

---

## 九、刪除後如何重新部署？

👉 **完全沒問題**，流程一模一樣：

1. Cloud Run → 建立服務
2. 選 GitHub Repo
3. 部署
4. 記得重新設定：
   - ✅ 允許未驗證存取
   - ✅ `OPENAI_API_KEY`

---

## 十、常見錯誤速查表

| 錯誤訊息 | 原因 | 解法 |
|------|------|------|
| Failed to listen on PORT 8080 | 沒用 `$PORT` | 修正 uvicorn port |
| No module named requests | requirements.txt 少套件 | 補上並重新部署 |
| Failed host lookup | App 連錯 URL | 改用 Cloud Run 網址 |
| OPENAI_API_KEY not set | 沒設環境變數 | Cloud Run 設定 |

---

## ✅ 結論（你現在的正確用法）

- 平常：
  - Android App + 本地 / mock backend
- 要 demo / 真實用：
  - 部署 Cloud Run
- 用完：
  - **直接刪 Cloud Run（省錢）**

---

📌 建議：這份文件直接存成 `DEPLOY.md` 放在 GitHub Repo 裡

