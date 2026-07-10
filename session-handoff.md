# Session Handoff

> 最後更新：2026-07-11 02:40

## 這個 session 做了（F7）

- **F7 passing**：電子支付爬蟲 ×2（`python -m scraper.e_payment`）
  - **名單改為街口＋icash Pay**（原 LINE Pay＋街口，DECISIONS D8 / PRD R2 註記）：LINE Pay 官網無實質優惠內容（都在 app 內 SPA），偵察後經 Ryan 決定換 icash Pay
  - `scraper/sources/jkopay.py`：mkt.jkopay.com 活動總覽 → campaign 頁；內文從 Next.js RSC flight payload（`self.__next_f.push`）解碼抽中文文字段；標題/摘要取 og:title/og:description；效期只信標題與活動時間類標記（`full_scan=False`——街口幣到期樣板日期會毒化效期）
  - `scraper/sources/icashpay.py`：advertMessage 列表＋分頁＋明細（靜態頁）；首頁直接當第 1 頁用（不重抓 page/1，分頁改版也不漏第 1 頁）
  - `scraper/runner.py`：共用 runner（從 credit_card.py 抽出）；入庫層失敗也隔離＋rollback（不只 fetch 層）
  - `scraper/dates.py`：`parse_period_near`（markers 順序、窗口尾端不切數字、`full_scan` 開關）；預設 markers 加「活動時間」
  - 實跑 52 筆（街口 19/icash Pay 33）、5 輪 idempotent、exit 0；ingest 後 Chroma 275 offers/1799 chunks；檢索實測電支優惠進 top-3
- `/start` 涵蓋範圍文案已更新（信用卡三家＋街口、icash Pay）——**bot 要重啟才生效**

## 做到一半 / 已知未修

- 無半成品。已知限制／待辦：
  1. **循環活動效期會過時**：街口「5 號會員日」等每月循環活動抽到的是本期領券窗口（如 7/1–7/5），過期後要等下次爬蟲重跑才更新——排程爬蟲（cron）可解，F9 後考慮
  2. **icash Pay 分頁只從第 1 頁發現**：若日後分頁截斷（1 2 3 … 12），後面頁會漏抓且無警訊；街口 RSC payload 解析對改版較脆（D8 代價）
  3. **jkopay RSC chunk 若帶非 JSON 跳脫（\x）會整塊丟棄**：現況實測 19/19 campaign 都解得出來，未修
  4. **DB 路徑雙軌**：runner 用 `OFFER_RADAR_DB`、config/settings 用 `DATABASE_PATH`——F8/F9 統一進 config 時一併收（連同 bot 35s/api 30s 逾時常數兩處）
  5. **單一 PoliteClient 跨網域共用 1s 間隔**：來源多了以後可改 per-domain client＋平行抓，MVP 不動
  6. 測試側小債：`read_fixture` 在兩個測試檔重複（可抽 conftest.py）；skip-on-http-error 測試五份同構（可改直測 `_shared`）
  7. 前 session 遺留照舊：Ollama 閒置卸載（504 冷載入）、**bot token 建議 BotFather revoke**、`.env.example` 缺條目（F9）、504 zombie thread、Chroma 併發無保證
- 營運注意：**ingest（bge-m3 embedding 1799 chunks）約 30–40 分鐘**，背景跑完再驗 count；中途查詢 Chroma 會看到空 collection（rebuild 進行中的中間態，不是壞掉）
- 啟動順序：`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`

## 下一步（具體到可直接動手）

1. F8 OpenAI 切換支援：驗收 R6——`LLM_PROVIDER=ollama|openai` 下 R4 均過；openai 缺 `OPENAI_API_KEY` 啟動即 fail fast 明確錯誤
2. generator 抽象已在 `rag/generator.py`，確認介面後加 openai client 實作＋settings 開關；qwen3 的 prompt 配方（D6）在 OpenAI 模型上要重新驗證
3. 順手收：DB 路徑與逾時常數統一進 config（見上第 4 點）
