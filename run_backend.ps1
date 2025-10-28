# 啟動 Medical QA Backend
Write-Host "=== 啟動 Medical QA Backend ===" -ForegroundColor Green

# 切換到專案目錄（請確認這裡是 app.py 所在的資料夾）
Set-Location -Path "$PSScriptRoot"

# 啟動虛擬環境
Write-Host "啟動虛擬環境 (.venv)..." -ForegroundColor Yellow
. .\.venv\Scripts\Activate.ps1

# 執行 Uvicorn 伺服器
Write-Host "啟動 Uvicorn 伺服器..." -ForegroundColor Yellow
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# .\run_backend.ps1