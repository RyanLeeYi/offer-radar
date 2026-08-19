# offer-radar — 消費優惠比較 RAG

用自然語言問「去好市多刷哪張卡最划算」，系統從台灣信用卡／電子支付優惠中檢索、比較，並附上來源連結。

台灣的信用卡與電支優惠散在各家官網、隔週就改，要比較得自己一頁頁翻。offer-radar 把這些優惠爬進向量資料庫，用 RAG（Retrieval-Augmented Generation）讓你像聊天一樣問，回答只根據實際入庫的優惠、每個結論都標來源，查無資料時明說「沒有」而不編造。

> 這是一個作品集專案，目的是端到端自建一條 RAG pipeline（爬蟲 → 切塊 → embedding → 向量檢索 → 生成），涵蓋中文 embedding、防幻覺 prompt、local LLM 部署與供應商切換。

## 架構

```
  各家官網                                          使用者
  信用卡 × 3（國泰／台新／富邦）                        │
  電子支付 × 2（街口／icash Pay）                    Telegram
     │                                                │
     ▼  scraper/ （requests + BeautifulSoup）          ▼
  SQLite (data/offers.db)  ◀── 只 upsert、來源隔離   bot/ （只打 HTTP）
     │                                                │
     ▼  rag.ingest                                    ▼
  切塊 → embedding(bge-m3) → ChromaDB (data/chroma)  api/ （FastAPI）
     │                                                │
     └──────────────▶  rag/pipeline  ◀────────────────┘
        混合檢索（n-gram 精確匹配 + 向量）
        → 防幻覺 prompt → LLM（Ollama 預設 / OpenAI 可切換）
```

各層邊界嚴格分離（見 `docs/ARCHITECTURE.md`）：`scraper/` 不碰 `rag/`；ChromaDB 只經 `rag/vector_store.py`；`api/` 只呼叫 `rag/pipeline.py`；`bot/` 只打 HTTP。

| 層 | 技術 |
|----|------|
| 爬蟲 | requests + BeautifulSoup（靜態頁、AEM `.model.json`、Next.js RSC payload） |
| 原始資料 | SQLite |
| 向量資料庫 | ChromaDB |
| Embedding | sentence-transformers（`BAAI/bge-m3`，multilingual，local） |
| 檢索 | 混合制：中文 n-gram `$contains` 精確匹配 + 向量相似度 |
| LLM | Ollama `qwen3:8b`（預設，local）/ OpenAI（可切換） |
| API | FastAPI（Swagger 可測） |
| 介面 | Telegram Bot |
| 套件管理 | uv |

## 快速開始

**前置**：[uv](https://docs.astral.sh/uv/)、Python ≥ 3.11、[Ollama](https://ollama.com/)（預設 LLM；用 OpenAI 則免）。

```bash
# 1. 環境（依賴 + .env + 煙霧測試）
./init.sh

# 2. 拉 local 模型（用 OpenAI 可跳過）
ollama pull qwen3:8b

# 3. 爬優惠進 SQLite（禮貌爬蟲：自報 UA、請求間隔 ≥ 1 秒）
uv run python -m scraper.credit_card    # 國泰、台新、富邦
uv run python -m scraper.e_payment      # 街口、icash Pay

# 4. 向量化入庫（切塊 → embedding → ChromaDB，首跑會下載 bge-m3）
uv run python -m rag.ingest

# 5. 問問題（CLI）
uv run python -m rag.query "去好市多刷哪張卡最划算"
```

## 使用

三種介面，同一條 pipeline：

**CLI**
```bash
uv run python -m rag.query "便利商店有什麼行動支付優惠"
```

**HTTP API**（FastAPI）
```bash
uv run uvicorn api.main:app          # Swagger UI: http://localhost:8000/docs
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "去好市多刷哪張卡最划算"}'
# GET /health 回 {ok, offers_count, last_ingest_at}
```

**Telegram Bot**（`.env` 填 `TELEGRAM_BOT_TOKEN` 後）

一鍵啟動三個 process（Ollama → API → Bot）：
- **啟動**：雙擊 `run.bat`（或 PowerShell 跑 `./run.ps1`）
- **關閉**：在視窗按 `Ctrl+C`，或雙擊 `stop.bat`

或手動分開起：
```bash
ollama serve
uv run uvicorn api.main:app          # bot 打這個 API
uv run python -m bot.main            # long polling
```

### 範例問答

| 問 | 系統行為 |
|----|----------|
| 去好市多刷哪張卡最划算 | 檢索相關優惠，比較後給結論並標【資料 N】來源 |
| 便利商店有什麼行動支付優惠 | 彙整街口／icash Pay 的超商通路優惠 |
| 去火星旅遊要刷哪張卡 | 查無相關資料 → 明說「目前資料庫沒有相關優惠資訊」、不編造 |

## LLM 供應商切換

預設 local Ollama，改用 OpenAI 只需環境變數：

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...        # 未填時服務啟動即失敗（fail fast，不拖到查詢時）
OPENAI_MODEL=gpt-4o-mini
```

## 測試

```bash
uv run pytest                # 158 tests
uv run pytest --cov=.        # coverage 90%
uv run ruff check .
```

爬蟲解析全部用本地 HTML fixture，測試不打真站。

## 設計取捨（詳見 `docs/archive/` 與開發紀錄）

- **純向量檢索對精確商家名有天花板**——「好市多」的正解藏在長條款 chunk 裡，換三種 embedding 都排不進 top-k。改用**混合檢索**（中文 n-gram 精確匹配 + 向量），關鍵詞命中免距離門檻。
- **防幻覺兩道防線**——檢索門檻做 sanity check，真正的防線是 prompt 指令要求「資料都無關才拒答」+ pipeline 層清空 sources。實測 `qwen3:8b` 對 prompt 位置敏感（拒答句放 system role 會無條件拒答），配方是逐次實驗調出來的。
- **常駐 API + 批次 ingest 的狀態共享**——ingest 全量重建 ChromaDB collection 會換 UUID，常駐 API 若快取 collection handle 會在 ingest 後全部失效。解法是不快取 handle、每次 `get_or_create`。
- **驗收條款在資料邊界就擋**——`Offer` 模型在 `__post_init__` 強制必填欄位與 source_type 契約，不等到查詢才發現資料殘缺。

## 現況與限制（MVP）

- **資料非即時**：手動跑爬蟲更新，不做查詢時即時爬取、不做自動排程。
- **來源涵蓋**：信用卡 3 家、電支 2 家。LINE Pay（優惠全在 app 內 SPA）、玉山（WAF 擋非瀏覽器請求）需 headless browser，列為後續。
- **循環活動效期**：每月循環的活動抓到的是當期窗口，過期需重跑爬蟲更新。
- 不做網頁前端、使用者帳號、回饋金額精確試算——Telegram Bot 是唯一介面，LLM 給比較說明不做數學保證。
