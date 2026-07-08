# offer-radar — Architecture

> 最後更新：2026-07-08（F1 完成時點；未實作的層標【規劃】）

## 資料流

```
[scraper/] ──寫──> SQLite (data/offers.db)
                      │
                      ▼ rag.ingest【規劃 F3】
              切塊 → embedding → ChromaDB (data/chroma)
                      │
                      ▼ 檢索【規劃 F4】
[bot/]【F6】─HTTP─> [api/]【F5】─> rag.pipeline【F4】─> LLM (Ollama/OpenAI)【F4/F8】
```

## 各層職責與邊界（違規 = 錯）

| 層 | 職責 | 允許依賴 | 禁止 |
|----|------|----------|------|
| `scraper/` | 爬取 + 資料模型 + SQLite 存取 | stdlib、requests、bs4 | import `rag/` `api/` `bot/` |
| `rag/`【規劃】 | chunker / embedder / vector_store / retriever / generator / pipeline | `scraper.db`（讀）、chromadb、sentence-transformers | ChromaDB 只能經 `rag/vector_store.py`；不 import `api/` `bot/` |
| `api/`【規劃】 | FastAPI 端點 + Pydantic schema | `rag.pipeline` | 直接碰 SQLite / ChromaDB |
| `bot/`【規劃】 | Telegram 介面 | HTTP 呼叫 api（requests/httpx） | import `rag/`、直接碰資料層 |
| `config/`【規劃】 | pydantic-settings 環境變數 | — | 密鑰硬編碼 |

## 已實作（F1）

- `scraper/models.py` — `Offer` frozen dataclass。驗證集中在 `__post_init__`：
  title/content/source_url 非空、source_type ∈ {credit_card, e_payment}、
  credit_card 必有 bank、e_payment 必有 provider（PRD R1/R2 在資料邊界就擋）
- `scraper/db.py` — schema 常數 + `init_db`（冪等、自建父目錄）/ `upsert_offer`
  （UNIQUE(source_url, title) ON CONFLICT UPDATE）/ `list_offers` / `count_offers`。
  日期存 ISO 字串，讀出還原成 date/datetime

## 慣例

- 不可變資料：一律建新物件（frozen dataclass），不原地改
- 測試不打真實網站：爬蟲解析用本地 HTML fixture
- data/ 不進 git；.env 不進 git（模板：.env.example）
