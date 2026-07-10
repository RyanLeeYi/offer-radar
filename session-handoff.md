# Session Handoff

> 最後更新：2026-07-11 01:05

## 這個 session 做了（F5 + F6）

- **F5 passing**：FastAPI `POST /query` + `GET /health`。詳見 feature_list evidence 與 DECISIONS D7（VectorStore 不快取 collection handle、ingest stats 存 collection metadata）
- **F6 passing**：Telegram Bot **@ryan_offer_radar_bot**（`python -m bot.main`，long polling）
  - `bot/api_client.py`：唯一後端出口（HTTP 打 FastAPI，不 import rag/、api/）；連線層錯誤統一轉 `ApiUnavailableError`
  - `bot/handlers.py`：文字→/query（answer+來源連結）、/start（範例問題+涵蓋範圍+資料更新日，資料來自 /health）、非文字→請用文字提問；422/503/504/連線失敗都有友善中文訊息；回覆硬上限 4096
  - `bot/main.py`：缺 token 啟動即 fail fast；**filter 鎖 `UpdateType.MESSAGE`**（不鎖的話 edited_message/channel_post 會進 handler 且 update.message 是 None——code review 抓到並以真 PTB Update 物件寫回歸測試）
  - Ryan 已在 Telegram 實測 R7 三行為 + 504 冷載入路徑

## 做到一半 / 已知未修

- 無半成品。已知限制／待辦：
  1. **Ollama 閒置 5 分鐘卸載模型**：冷掉後第一問必吃 504（bot 有友善訊息引導重試）。改善選項：generator payload 加 `keep_alive`、API 啟動時預熱、或接受現狀——F8/F9 時決定
  2. **TELEGRAM_BOT_TOKEN 曾出現在對話記錄**：建議找 BotFather `/revoke` 換新 token（.env 更新即可，程式不用改）
  3. F7 上線時要同步改 `bot/handlers.py` 的 `/start` 涵蓋範圍文案（目前寫死「國泰、台新、富邦信用卡優惠」）
  4. bot 35s / api 30s 逾時常數兩處手動對齊（有註解互指），F8/F9 統一進 config 時一併收
  5. F5 遺留：504 zombie thread 佔 threadpool、Chroma client 併發無明文保證（MVP 不修）
  6. `.env.example` 缺 `EMBEDDING_MODEL`、`TELEGRAM_BOT_TOKEN` 條目說明（F9）
- 啟動順序：`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`

## 下一步（具體到可直接動手）

1. F7 電子支付爬蟲 ×2（LINE Pay、街口）：驗收 R2——`python -m scraper.e_payment` 後 ≥10 筆、provider 欄位標支付業者、其餘行為同 R1（upsert 去重、單來源失敗隔離、非 0 exit）
2. 動工前先做可爬性偵察（F2 的教訓：名單可能要換，先確認再寫解析器；猜 URL 兩次不中就換工具）
3. 復用 `scraper/sources/_shared.py` 管線與 `scraper/http.py`；fixture 測試不打真站
4. 完成後跑一輪 `python -m rag.ingest` 讓電支優惠進庫，並更新 `/start` 涵蓋範圍文案（見上）
