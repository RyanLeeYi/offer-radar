#!/bin/bash
set -e
# 目標：全新 clone 或換機後，跑這一支就能到「可開發、可驗證」狀態

# 1. 依賴（需要 uv：https://docs.astral.sh/uv/）
uv sync

# 2. 環境變數
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  已從 .env.example 建立 .env——請填入 TELEGRAM_BOT_TOKEN（F6 前）與 OPENAI_API_KEY（F8、選用）"
fi

# 3. 本地資料目錄
mkdir -p data

# 4. 煙霧測試：環境是活的
uv run pytest -q

echo "init OK"
