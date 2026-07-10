# offer-radar — 消費優惠比較 RAG 系統

台灣信用卡/電子支付優惠爬取 + ChromaDB 向量檢索 + Telegram Bot 自然語言查詢。
規格：`docs/prd/PRD - 消費優惠比較RAG.md`（驗收標準 R1–R7 以此為準）。

## 啟動與驗證

- 環境恢復：`./init.sh`（uv sync + .env 準備 + 煙霧測試）
- 測試：`uv run pytest`；lint：`uv run ruff check .`
- 啟動 API：`uv run uvicorn api.main:app --reload`
- **你宣告任何功能完成前，必須先跑過測試命令並貼出輸出**

## 專案結構與邊界

| 目錄 | 職責 | 邊界規則 |
|------|------|----------|
| `scraper/` | 爬蟲 + 資料模型，寫 SQLite | 不得 import `rag/`、`api/`、`bot/` |
| `rag/` | chunker / embedder / vector_store / retriever / generator / pipeline | ChromaDB 只能經 `rag/vector_store.py` 操作 |
| `api/` | FastAPI 端點 + Pydantic schema | 只呼叫 `rag/pipeline.py`，不直接碰 ChromaDB/SQLite |
| `bot/` | Telegram Bot | 只呼叫 FastAPI（HTTP），不 import `rag/` |
| `config/` | 環境變數管理（pydantic-settings） | 密鑰只從 .env 讀，一律不硬編碼 |

## 工作規則

1. 一次只做一個 feature（看 `feature_list.json`，挑第一個 failing）
2. TDD：先寫測試（RED）→ 實作（GREEN）→ 重構；覆蓋率 ≥ 80%
3. feature 狀態只能 failing → passing，且必須附驗證證據（測試輸出）；沒有 evidence 不准改 passing
4. 不做 feature_list 之外的事；發現新事項 → 先加進 list 標 failing，不直接做
5. 每個 feature 完成後跑 `/code-review`
6. 爬蟲禮儀：遵守 robots.txt、自訂 User-Agent、請求間隔 ≥ 1 秒
7. `reward_rate` 保留原文不解析（PRD 技術約束）
8. session 結束前更新 `session-handoff.md`（L2 起）
9. 收官（session 結束）時檢查 `git status` + 未推 commit：程式碼有改動就 commit 並 `git push`（remote：github.com/RyanLeeYi/offer-radar）
