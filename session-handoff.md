# Session Handoff

> 最後更新：2026-08-23（無人看管 session，由 agent-brief-me 派出）

## 這個 session 做了（F11–F15 web 網搜補資料 epic 全數實作完成）

開場時 F11/F12 的實作已在 HEAD（前一場留下）但狀態仍 failing；F13–F15 連規格都沒簽核。
inbox 的 11 筆答案全是 "Sign off as-is" ＋ "Run, start with F11"，據此簽核 F13–F15 後動工。

### F11 / F12 — passing 並歸檔
`acceptance-verifier` fresh context 逐條 7/7 pass，無 fail 項。整條原文已搬進
`docs/archive/features.jsonl`，主檔只留 failing。

### F13 — 查詢正規化 + Tavily 搜尋 + LLM 抽取（executor worktree 產出，主 session 整合）
> 狀態：passing 並歸檔（重驗 6/6）
- `rag/llm.py`：`build_completion(settings)` → `LlmFn = Callable[[str], str]`，通用「prompt → 文字」
  介面（`rag/generator.py` 的 `generate(question, hits)` 綁死 RAG 回答，抽取端用不了）
- `rag/web_search.py`：`TavilySearch`（`post` 可注入）、`build_search` 缺 key fail fast
- `rag/extractor.py`：`normalize_query` / `build_search_terms` / `extract_offers`，
  抽取 prompt 獨立、輸出過 Pydantic、語意驗證重用 `Offer.__post_init__`
- **主 session 整合時改了兩處 worker 的判斷**：
  1. Tavily 認證改成 `Authorization: Bearer`——worker 把 key 放進 body 的 `api_key`，
     那是舊式整合寫法，現行 API reference（Context7 查證）用 header。沒有 key 測不出來，
     會等到 Ryan 第一次實跑才 401
  2. `Entity` 加 `official_domain`（LLM 推測），否則 acceptance 的「include_domains 優先官網」
     沒有任何路徑餵得到值

### F14 — unverified 警語
> 狀態：passing 並歸檔（3/3）
- `UNVERIFIED_WARNING` 在 `rag/pipeline.py`，**逐條列出未驗證的標題**，verified 條目不連坐
- 警語判定看整個 context（未截斷），不是看截斷後的 5 筆 sources——LLM 可能引用排第 6 名以後的資料
- `build_user_content` 把未驗證資料標成 `【資料 N｜未經驗證】`；全 verified 時 prompt 逐字元不變

### F15 — 背景補查 job
> 狀態：passing 並歸檔（重驗 6/6）
- `rag/backfill.py`：`python -m rag.backfill`，miss_log → 正規化 → 網搜 → 抽取 → 入庫 →（有新資料才）ingest
- 拒答句改成「目前資料庫沒有相關優惠資訊。已記下這個問題、稍後補查。」
- 端到端測試走真 SQLite + 真 ChromaDB（`tests/test_backfill.py::test_end_to_end_...`）

### `/code-review` 抓到 7 項，FIX 5 / DEFER 2
FIX（都已修，各留一條會紅的回歸測試）：
1. **抽不出 entity 的 miss 餓死後續 miss**（P1）：`pending` 取前 `limit` 筆 entity IS NULL，
   抽不出的永遠留 NULL → 累積 20 筆之後 job 每輪白燒 20 次 LLM 呼叫、什麼都做不了。
   改標 `UNRESOLVED = "?"`
2. **web_unverified 覆蓋 verified**（P1）：upsert key 是 `(source_url, title)`，網搜撞上爬蟲
   已收的同一筆會把它降級並掛 7 天 TTL，到期後連原本的爬蟲資料都被 `list_active_offers` 濾掉。
   守門加在 `scraper/db.py` 的共用寫入路徑（`ON CONFLICT ... WHERE NOT (...)`），不是只擋 backfill
3. `official_domain` 沒寫進 normalize prompt（P2）→ include_domains 是死路
4. `_SKIPPABLE_ERRORS` 接不到 `openai.APIError`（P2）→ 一次 429 炸掉整批
5. `searched` 計 entity 數但額度算的是請求數（P3，最壞 limit×4）→ 加 `requests` 欄位

DEFER（P3，記在這裡不另開 feature）：
- 24h 去重用 miss 的 `created_at` 近似「搜過的時間」，被 limit 擋在窗外的 miss 可能提早重搜
- `rag/llm.py` 與 `rag/generator.py` 的 provider 選擇／think 剝除／timeout 重複一份
  （當初為了讓 worker 與主 session 檔案不重疊而分開，之後可合流）

## 驗收與流程

**F11-F15 五條全部 passing 並歸檔，`feature_list.json` 的 features 已空。** 下一條 feature 要自己開。

驗收踩到一次流程坑：第一輪 F13/F14/F15 驗收跑到一半時，主 session commit 了 `/code-review` 的
修正，害它的基準（`75de002`）與 HEAD（`56f7da6`）分岔——那一輪等於白跑，還得再派一次針對性重驗。
**驗收 worker 是對著工作樹現況驗的，不是對著某個 commit：驗收期間主工作區要凍結。**

值得記的是兩個獨立檢查（`/code-review` 與 acceptance-verifier）各自抓到同一條 P1，
而且都是靠「拿一個只回 prompt 實際要求欄位的合規假 LLM 實跑」看穿的——
測試綠燈是因為 fixture 手動塞了 prompt 從沒要求的欄位。**fixture 餵什麼、prompt 要什麼，是兩件事。**

## 做到一半 / 已知未修

1. **沒有任何一次真實的 Tavily 呼叫發生過**——`.env` 沒有 `TAVILY_API_KEY`，所有網搜與 LLM
   都是注入假件。串接正確性證明得了，「Tavily 回不回得出台灣優惠網頁、抽取 prompt 對真實
   網頁管不管用」證明不了。**已投 inbox question 請 Ryan 裁決**（申請 key：app.tavily.com，
   免費 1000 次/月）。填進 `.env` 後跑 `uv run python -m rag.backfill` 就看得到真實結果
2. 前 session 遺留照舊：`LLM_PROVIDER=openai` 真 API 手動驗一次、F16 Telegram 端真機驗 edit、
   DB 路徑雙軌（`OFFER_RADAR_DB` vs `DATABASE_PATH`）、bot 95s/api 90s 逾時常數兩處
3. `rag/backfill.py` 沒有排程——目前只能手動跑。要固定補查得自己掛 cron／排程任務
4. 營運注意不變：ingest（bge-m3，1799 chunks）約 30–40 分鐘；`backfill` 只在有新資料時才觸發 ingest

## 下一步（具體到可直接動手）

1. **等 inbox 答覆**：Tavily key 要不要申請（決定 F13/F15 能不能標 passing）
2. key 到位後：`uv run python -m rag.backfill` 實跑一次，看 `requests=` 與 `stored=`，
   確認抽取 prompt 對真實網頁管用；不管用就調 `_EXTRACT_INSTRUCTIONS`
3. bot／API 要重啟才吃得到新的拒答句與警語
4. 順手可收：上面 DEFER 的兩項技術債

## 啟動順序（不變）

`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`
