# 一鍵啟動 offer-radar：Ollama（若未跑）→ FastAPI → Telegram Bot。
# 用法：pwsh -File run.ps1（或在 PowerShell 直接 ./run.ps1）
# 按 Ctrl+C 關閉本腳本啟動的所有 process。log 寫進 logs/。
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$OllamaUrl = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { "http://localhost:11434" }
$ApiUrl    = if ($env:API_BASE_URL)    { $env:API_BASE_URL }    else { "http://localhost:8000" }
New-Item -ItemType Directory -Force -Path logs | Out-Null

# venv 執行檔（Windows 在 Scripts/）——直接呼叫，Start-Process -PassThru 回真 Windows PID
$VenvBin = Join-Path $PSScriptRoot ".venv\Scripts"
if (-not (Test-Path (Join-Path $VenvBin "python.exe"))) {
    Write-Host "找不到 .venv——先跑 ./init.sh 建好環境" -ForegroundColor Red
    exit 1
}

$started = @()  # 本腳本啟動的 process 物件

function Test-Up([string]$Url) {
    try { Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing | Out-Null; return $true }
    catch { return $false }
}

function Wait-Up([string]$Url, [string]$Name, [int]$Limit) {
    for ($i = 0; $i -lt $Limit; $i++) {
        if (Test-Up $Url) { return }
        Start-Sleep -Seconds 1
    }
    Write-Host "$Name 在 ${Limit}s 內沒起來，看 logs\ 找原因" -ForegroundColor Red
    throw "$Name 啟動逾時"
}

function Start-Bg([string]$File, [string[]]$ArgList, [string]$Log) {
    Start-Process -FilePath $File -ArgumentList $ArgList -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput "logs\$Log.log" -RedirectStandardError "logs\$Log.err"
}

try {
    # 1. Ollama：已在跑就沿用，否則背景啟動
    if (Test-Up "$OllamaUrl/api/tags") {
        Write-Host "Ollama 已在跑（$OllamaUrl）" -ForegroundColor Green
    } else {
        Write-Host "啟動 Ollama…"
        $started += Start-Bg "ollama" @("serve") "ollama"
        Wait-Up "$OllamaUrl/api/tags" "Ollama" 30
        Write-Host "Ollama 就緒" -ForegroundColor Green
    }

    # 2. FastAPI（bot 打這個）
    Write-Host "啟動 FastAPI…（首次啟動要載入 embedding 模型，可能等 ~30-60s）"
    $started += Start-Bg (Join-Path $VenvBin "uvicorn.exe") @("api.main:app") "api"
    Wait-Up "$ApiUrl/health" "FastAPI" 90
    Write-Host "FastAPI 就緒（$ApiUrl，Swagger：$ApiUrl/docs）" -ForegroundColor Green

    # 3. Telegram Bot
    Write-Host "啟動 Telegram Bot…"
    $started += Start-Bg (Join-Path $VenvBin "python.exe") @("-m", "bot.main") "bot"
    Write-Host "Bot 已啟動——打開 Telegram 傳訊息給你的 bot" -ForegroundColor Green
    Write-Host ""
    Write-Host "全部就緒。即時 log：Get-Content logs\bot.log -Wait（或 api / ollama）"
    Write-Host "按 Ctrl+C 關閉全部。"

    while ($true) { Start-Sleep -Seconds 3600 }
}
finally {
    Write-Host ""
    Write-Host "關閉中…"
    foreach ($p in $started) {
        # /T 連子 process 一起殺（uvicorn.exe 會 spawn python child，只殺父殺不乾淨）
        taskkill /PID $p.Id /T /F 2>$null | Out-Null
    }
    Write-Host "已全部關閉。"
}
