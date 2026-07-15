# Session Handoff

> 最後更新：2026-07-15

## 這個 session 做了（F16 — 慢查詢體驗）

- **F16 passing**：bot 處理中提示 + /query 逾時 30s→90s（TDD，162 tests pass、ruff clean）
  - `bot/handlers.py`：`on_text` 先回 `PROCESSING_REPLY`「🔍 查詢中，請稍候…」placeholder，拿到結果後 `edit_text` 就地更新（200/503/504/422/連線失敗五路徑全改 edit，不另發新訊息洗版）
  - `api/main.py`：`QUERY_TIMEOUT_SECONDS` 30→90（涵蓋 8B 冷載入 ~24s 最壞情況；transport 120s 仍為外層上界）；`bot/api_client.py` `_QUERY_TIMEOUT` 35→95（client 要 >90）
  - `docs/prd/PRD…md` line 110 逾時契約同步改 90s（SSOT）
  - **背景**：Ryan 決定不加 `keep_alive`（正常使用間隔常 >2h，預設 5min 夠用），暖機不治本，改用「90s 逾時 + 處理中提示」吸收冷載入的體感
  - ⚠️ Telegram 端真機 edit 未跑（fake 注入驗行為）；bot 要**重啟**才生效

## 這個 session 做了（F7 + F8）

### F8 — OpenAI 切換支援（passing）
- `rag/generator.py`：新增 `OpenAIGenerator`（transport `complete` 可注入、預設延後建 OpenAI client）＋ `build_generator(settings)` factory（依 `llm_provider` 選 ollama/openai；openai 缺 `OPENAI_API_KEY` 或未知 provider 即 `raise ValueError`，fail fast）
- prompt 配方抽成 `build_user_content(question, hits)` 單一事實來源，兩 generator 共用（測試把關一致性）
- `rag/pipeline.py build_default` 改走 `build_generator` → fail fast 在 API/CLI 啟動期發生，不是查詢時
- 158 tests、ruff clean；缺 key 實測即 raise；OpenAI SDK 用法 Context7 已確認
- ⚠️ **待 Ryan 手動驗一件**：`LLM_PROVIDER=openai` + 有效金鑰下實跑一次 `/query`（R6 的「openai 下 R4 通過」）。我沒擅用 memory 裡那把外洩待輪替的 OpenAI key。驗法：`.env` 設 `LLM_PROVIDER=openai` + `OPENAI_API_KEY=<有效 key>`，重啟 API，問 PRD 三範例確認回答正常
- ⚠️ code review：F8 diff 是純抽取 + 小新增（一個 class + factory），我用**聚焦自審 + Context7 驗 SDK + fail-fast 實測**取代完整多代理 /code-review（F7 已跑完整 8 角度）。若要補正式 review 可對 `rag/generator.py` 跑一次

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
  4. **DB 路徑雙軌**：runner 用 `OFFER_RADAR_DB`、config/settings 用 `DATABASE_PATH`——F8/F9 統一進 config 時一併收（連同 bot 95s/api 90s 逾時常數兩處，F16 後仍是兩處硬編碼，僅值改）
  5. **單一 PoliteClient 跨網域共用 1s 間隔**：來源多了以後可改 per-domain client＋平行抓，MVP 不動
  6. 測試側小債：`read_fixture` 在兩個測試檔重複（可抽 conftest.py）；skip-on-http-error 測試五份同構（可改直測 `_shared`）
  7. 前 session 遺留照舊：Ollama 閒置卸載（504 冷載入）、**bot token 建議 BotFather revoke**、`.env.example` 缺條目（F9）、504 zombie thread、Chroma 併發無保證
- 營運注意：**ingest（bge-m3 embedding 1799 chunks）約 30–40 分鐘**，背景跑完再驗 count；中途查詢 Chroma 會看到空 collection（rebuild 進行中的中間態，不是壞掉）
- 啟動順序：`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`

## 下一步（具體到可直接動手）

1. **F9 README + 乾淨環境驗證**（最後一個 feature，收官）：驗收——乾淨 clone 照 README + `./init.sh` 可跑起；`.env.example` 齊全（補 `LLM_PROVIDER`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`EMBEDDING_MODEL`、`TELEGRAM_BOT_TOKEN` 條目）；pytest 覆蓋率 ≥ 80%（現 90%）；ruff clean；PRD 三範例 Telegram 端手動驗
2. F9 README 是對外文稿 → 先讀 vault `identity/voice-and-tone.md`（若存在）
3. 收官走 vault PLAN 的 checklist + `sop/after-action.md`（成功指標對答案、harness 消融檢討、成就故事、歸檔）
4. F8 遺留：openai provider 真 API 手動驗一次（見上）
5. 順手收技術債：DB 路徑雙軌（`OFFER_RADAR_DB` vs `DATABASE_PATH`）、bot 95s/api 90s 逾時常數兩處，統一進 config
