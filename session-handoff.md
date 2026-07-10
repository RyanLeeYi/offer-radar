# Session Handoff

> 最後更新：2026-07-11 00:55

## 這個 session 做了（F5）

- **F5 passing**：FastAPI `POST /query` + `GET /health`（`uv run uvicorn api.main:app`）。PRD R4+R5 全驗收：422/503/504 邊界、Swagger、真庫三範例實測，acceptance-verifier 逐條 PASS
  - `api/main.py` 薄封裝：只 import `rag/pipeline.py`；注入走 `RagRuntime` 一包（pipeline+stats 必成對）；30 秒逾時契約在這層（`asyncio.wait_for` + `to_thread`），transport 層維持 120s 容冷載入
  - `api/schemas.py`：question 1–500 字 Pydantic 驗證；`SourceOut` 用 `from_attributes` 直接吃 rag 的 `Source`；503/504 統一 `ErrorResponse` 形狀
  - **code review 抓到的關鍵修正（D7）**：`VectorStore` 不再快取 Chroma collection handle（每次 `get_or_create`）——否則常駐 API 遇到另一 process 跑 ingest rebuild 就永久 NotFoundError；ingest stats（`last_ingest_at` + `offers_count`）存 collection metadata，/health 免全量掃 1531 chunks
  - `rag/pipeline.build_default()`：CLI 與 API 共用的組裝入口（query.py 的 build_pipeline 上移）

## 做到一半 / 已知未修

- 無半成品。已知限制（code review PLAUSIBLE，MVP 不修）：
  1. **504 zombie thread**：逾時後 pipeline thread 繼續跑滿 transport 120s，佔 default threadpool（上限 min(32, cpu+4)）；Ollama 降速期連續逾時可耗盡 pool → 連鎖 504。要修：semaphore 閘門或可取消的 HTTP client
  2. **Chroma client 併發**：多執行緒打同一 PersistentClient 無明文 thread-safety 保證，高並發可能 database is locked
  3. `last_ingest_at` 時鐘不可注入（ingest 的 today 可以），測試只驗 ISO 可解析
  4. F2 遺留：台新/富邦 load-more 覆蓋率缺口、robots 程式化檢查；F4 遺留：$contains 破萬筆換 FTS
  5. 本機 `.env` 設 `OLLAMA_MODEL=qwen3:8b`（config 預設仍 llama3.1:8b）；`.env.example` 缺 `EMBEDDING_MODEL`（F9 統一檢討）
- Ollama 要手動起（`ollama serve`）；qwen3:8b 冷載入 ~24s，冷查詢可能吃到 504（重試即可，屬設計內）
- 真庫已重 ingest（2026-07-10T23:42:51+08:00，228 優惠 → 1531 chunks），collection metadata 已帶 ingest stats

## 下一步（具體到可直接動手）

1. F6 Telegram Bot（bot/ 只打 FastAPI HTTP，不 import rag/）：文字訊息 → POST /query 回 answer+來源連結；`/start` 使用說明（能問什麼、資料涵蓋範圍、資料更新日——更新日可打 /health 拿 last_ingest_at）；非文字訊息回「請用文字提問」
2. `TELEGRAM_BOT_TOKEN` 已在 config/settings.py 預留，.env 要補真 token（找 BotFather 建）；token 不進 repo
3. 測試：python-telegram-bot 的 handler 單元測試 + 假 API client 注入；手動驗證要真 Bot 跑一輪 PRD 三範例（F9 完成定義要求 Telegram 端）
4. API 啟動順序：ollama serve → uvicorn → bot（bot 起來前先打 /health 確認 API 活著）
