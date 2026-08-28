# Session Handoff

> 最後更新：2026-08-28（無人看管 session，agent-brief-me 派工）

## 目前狀態

- **321 tests / ruff clean**
- `feature_list.json` 剩 **F20**（openai 真 API 驗證，blocked：需要 Ryan 提供
  `OPENAI_API_KEY`，會產生費用）與 **F27**（API_BASE_URL 要不要比照改 127.0.0.1，
  **未簽核**，等 Ryan 裁決）。F26 已 passing 並歸檔進 `docs/archive/features.jsonl`
- 08/27 handoff 裡那條「待 Ryan 裁決：OLLAMA_BASE_URL 要不要改 127.0.0.1」**已裁決並落地**（F26）

## 這個 session 做了

**F26（ollama 預設位址改 127.0.0.1）passing 歸檔。** 來源是 Ryan 在 brief-me 對
question `59574c87` 選的「改掉預設值（127.0.0.1）」——也就是上一場 F25 留下的待裁決項。

改動只有預設值與註解，沒動任何呼叫路徑的邏輯：

- `config/settings.py` 的 `ollama_base_url` 預設 → `http://127.0.0.1:11434`
- `.env.example` 的 `OLLAMA_BASE_URL` 同步，並註明「要用 localhost 就在這裡改回來」
- `tests/test_settings.py` 兩條斷言釘住：預設值是 127.0.0.1、且 `OLLAMA_BASE_URL`
  仍覆寫得回 localhost（**沒有把 localhost 封死**——ollama 只監聽 IPv6 的環境要活得下去）
- `rag/llm_provider.py` 與 `tests/test_provider_health.py` 只改 `PS_TIMEOUT` 的**理由註解**：
  10 秒餘裕現在是為了「`.env` 可能覆寫回 localhost」而留，不是為了預設值。值維持 10.0

### 為什麼沒順手把 `API_BASE_URL` 一起改（下一個 agent 別再問一次）

`config/settings.py` 的 `api_base_url` 與 `.env.example` 的 `API_BASE_URL` 預設同樣是
`http://localhost:8000`，**bot 每次呼叫 `/query` 吃的是同一個 2 秒成本**，同一個根因。
沒有一起改是因為 Ryan 的裁決逐字只涵蓋 ollama 端，不是因為沒看到。已開 **F27** 標
`failing` + 未簽核並投了 sign-off 卡；Ryan 點頭就是同一種兩行改動。

### 驗證證據

- 主 session 實測（真 transport）：`check_ollama` 走 `127.0.0.1` **0.000s**、走 `localhost`
  **2.046s**，兩者都 pass ——省下的 2 秒是每次 LLM 呼叫都在付的
- `uv run pytest -q` → **321 passed**（+1）；`uv run ruff check .` → clean
- fresh-context `acceptance-verifier` 逐條 **6/6 pass、零 finding**。驗收者不吃我的說法：
  親自跑 Python 驗兩個覆寫方向、用 `git diff` 確認 `rag/llm.py`／`rag/pipeline.py`／
  `api/main.py`／`bot/` 的 diff 為空、並用 socket 與 httpx 兩層獨立複驗前提
  （socket：localhost 2.044s／2.139s vs 127.0.0.1 0.000s）

## 下一步

1. **F27**：等 Ryan 對 `API_BASE_URL` 的裁決（已投 brief-me sign-off 卡）。核准後改兩處
   預設 + 兩條測試，形狀與 F26 完全一樣
2. **F20**：Ryan 填 `OPENAI_API_KEY` 後照 acceptance 跑一次真 API 驗證。
   acceptance 最後一步要切回 ollama 驗 `/query`——現在若 ollama 出不了 token，
   會**秒回 504 + 診斷訊息**而不是空等 90 秒，卡點會直接告訴你是哪一種。
   仍建議開跑前先看 `ollama ps` 的 PROCESSOR 欄，`%CPU` 佔多數就是 08/25 那個坑
   （RAM 耗盡 → 退回 CPU → thrash），先關掉 Docker/WSL/其他 session 再驗
3. 想讓 PTT 定期入庫：把 `rag/ptt_ingest` 掛排程或接進 runner（開新 feature）

## 仍然成立的既有脈絡

- **`localhost` 在這台 Windows 每次多付約 2.0 秒**（先試 IPv6 `::1`，closed 端點約 2 秒才
  fallback 到 IPv4；`127.0.0.1` 是 0.016 秒以下）。看到任何新的本機位址設定，先想這件事
- PTT 資料源**尚未掛進 `scraper/runner.py` 正式排程**——跑批走 `python -m rag.ptt_ingest`
- PTT offer 刻意不設 TTL（`expires_at=None`），理由見 `rag/ptt_extractor.py` docstring
- Tavily 補查仍刻意關閉（Ryan 08/23 裁決）；拒答句「稍後補查」DEFER 條件不變
- `.env.example` 明寫 prompt 配方是針對 qwen3:8b 調的，換模型要重驗

## 啟動順序（不變）

`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`
