# Session Handoff

> 最後更新：2026-08-27（無人看管 session，agent-brief-me 派工）

## 目前狀態

- **320 tests / 90% coverage / ruff clean**
- `feature_list.json` 只剩 **F20**（openai 真 API 驗證），仍 blocked：需要 Ryan 提供
  `OPENAI_API_KEY`（會產生費用）。F25 已 passing 並歸檔進 `docs/archive/features.jsonl`
- 08/25 深夜記錄的「ollama 空等 90 秒」已由 F25 處理掉（見下）

## 這個 session 做了

**F25（ollama provider 健康預檢）passing 歸檔。** 來源是 Ryan 在 brief-me 對
question `3d4ef80f` 選的 (b) 立案。

`rag/llm_provider.py` 新增 `ProviderUnavailable` 與 `check_ollama()`，正式組裝路徑
（`build_generator` → `OllamaGenerator`）每次 generate 前跑：

- `/api/ps` 連不上 → 立刻 raise，訊息叫人去確認 `ollama serve`
- 模型不在已載入清單 → **冷啟動，直接放行不探測**（8B 冷載入約 24 秒，用短預算去探等於誤殺）
- 模型已載入 → `/api/generate` 吐 1 個 token 探測，5 秒沒回就 raise

`api/main.py` 把 `ProviderUnavailable` 轉 504 + 例外訊息（不是 500，也不空等 90 秒）。
直接建構、沒注入 check 的 `OllamaGenerator` 行為完全不變。bot 沒動。

### 實作期發現的一個坑（下一個 agent 值得知道）

**`http://localhost:11434` 在這台機器上每次要 2.0 秒，換成 `http://127.0.0.1:11434`
只要 0.016 秒。** Windows 先試 IPv6 `::1`，closed 端點要等約 2 秒才 fallback 到 IPv4。

這不是 F25 造成的——`rag/llm.py` 與所有既有 ollama 呼叫都在付這 2 秒。但它讓原本
訂的 `PS_TIMEOUT = 3.0` 只剩不到 1 秒餘裕，主機一忙就會誤報「連不上 ollama」，而
**主機忙正是這道預檢要處理的情境**。已改成 10.0 並加測試釘住餘裕。

> **待 Ryan 裁決（沒有動）**：要不要把設定預設的 `OLLAMA_BASE_URL` 從 `localhost`
> 改成 `127.0.0.1`，讓每次 LLM 呼叫都省下這 2 秒。這是跨 F25 範圍的設定變更，
> 影響 `rag/llm.py` 等所有既有路徑，所以留著沒做。

### 驗證證據

- `uv run pytest -q` → **320 passed**；`uv run ruff check .` → clean；coverage 90%
- fresh-context `acceptance-verifier` 逐條 **6/6 pass，無 finding**。驗收者不靠注入
  假件，自架假 HTTP server 真 transport 重現三分支：(a) 連不上 4.09s raise、
  (b) 對本機真 ollama（`models=[]`）冷啟動放行 2.05s 不探測、(c) 已載入吐不出 token
  5.00s raise；並用真 `Settings`→`build_generator`→`Pipeline`→`create_app` 打
  `/query`（`query_timeout=90`）確認回 504、elapsed 5.05s、答案不是拒答句
  （即 `Pipeline.answer` 沒把例外吞掉）

## 下一步

1. **F20**：Ryan 填 `OPENAI_API_KEY` 後照 acceptance 跑一次真 API 驗證。
   acceptance 最後一步要切回 ollama 驗 `/query`——現在若 ollama 出不了 token，
   會**秒回 504 + 診斷訊息**而不是空等 90 秒，卡點會直接告訴你是哪一種。
   仍建議開跑前先看 `ollama ps` 的 PROCESSOR 欄，`%CPU` 佔多數就是 08/25 那個坑
   （RAM 耗盡 → 退回 CPU → thrash），先關掉 Docker/WSL/其他 session 再驗
2. `OLLAMA_BASE_URL` 要不要改 `127.0.0.1`（見上方待裁決）
3. 想讓 PTT 定期入庫：把 `rag/ptt_ingest` 掛排程或接進 runner（開新 feature）

## 仍然成立的既有脈絡

- PTT 資料源**尚未掛進 `scraper/runner.py` 正式排程**——跑批走 `python -m rag.ptt_ingest`
- PTT offer 刻意不設 TTL（`expires_at=None`），理由見 `rag/ptt_extractor.py` docstring
- Tavily 補查仍刻意關閉（Ryan 08/23 裁決）；拒答句「稍後補查」DEFER 條件不變
- `.env.example` 明寫 prompt 配方是針對 qwen3:8b 調的，換模型要重驗

## 啟動順序（不變）

`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`
