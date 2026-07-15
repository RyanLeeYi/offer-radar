---
updated: 2026-07-07
tags: [prd, side-project, rag]
summary: 消費優惠比較 RAG 系統的需求規格——爬信用卡/電子支付優惠、ChromaDB 向量檢索、FastAPI、Telegram Bot
feature: TBD（動工日建 code repo 後轉 feature_list.json，本檔搬進 repo docs/prd/）
---

# 消費優惠比較 RAG 系統 — PRD

> 前身：[[消費優惠比較RAG-實作計畫]]（技術選型與時程依據）。本檔把該計畫逼成可驗證規格。

## 背景與目標

分析 5 個 AI 職缺後，最大缺口是 RAG 實作經驗（5/5 職缺要求）。本專案 1-2 週做出 MVP，一次補上：RAG pipeline、向量資料庫（ChromaDB）、Embedding 流程、FastAPI、local LLM（Ollama）。實用面：用自然語言查「去好市多刷哪張卡最划算」。

## 非目標（本次不做）

- 不做網頁前端 UI——Telegram Bot 是唯一使用者介面
- 不做使用者帳號與個人化（例如「只比較我持有的卡」）——MVP 全域查詢
- 不做查詢時即時爬取——只查已入庫資料
- 不承諾回饋金額精確試算——LLM 生成比較說明並附來源，數學計算不在驗收範圍
- 不做自動排程更新——MVP 手動跑爬蟲

## 需求與驗收標準

### R1：信用卡優惠爬蟲（國泰、台新、富邦）

> 2026/07/10 名單調整（原：國泰、中信、玉山）：中信全站反爬（混淆 JS 挑戰頁）出局；玉山列表 API 被 WAF 擋非瀏覽器請求、需 headless browser，暫緩。改為三家純 HTTP 可爬：國泰（cathay-cube sitemap + .model.json）、台新（mkpcard CMS 靜態頁）、富邦（cardpromote 專站靜態頁）。決策人：Ryan。

- Given 網路可用、SQLite 已初始化
- When 執行 `python -m scraper.credit_card`
- Then `offers` 表新增/更新 ≥ 30 筆，每筆必含 `title`、`content`、`source_url`、`bank`、`scraped_at`；`valid_to` 可為 null（頁面未標示時）
- Then 重複執行不產生重複資料（以 `source_url + title` 做 upsert key）

### R2：電子支付優惠爬蟲（街口、icash Pay）

> 2026/07/11 名單調整（原：LINE Pay、街口）：LINE Pay 官網活動頁僅 1 筆常青導流項，實質優惠全在 app 內 Nuxt SPA，requests 拿不到內容，出局。改為街口（mkt.jkopay.com campaign 頁，Next.js RSC payload 內嵌 HTML）＋ icash Pay（advertMessage 列表＋分頁＋明細，伺服器渲染）。決策人：Ryan。

- 同 R1 行為，`python -m scraper.e_payment` 後 ≥ 10 筆，`provider` 欄位標明支付業者

### R3：向量化入庫

- Given SQLite 有優惠資料
- When 執行 `python -m rag.ingest`
- Then ChromaDB collection 筆數 = SQLite 中「未過期」優惠筆數（`valid_to` 為 null 或 ≥ 今天）
- Then 每個 chunk 的 metadata 含 `offer_id`、`valid_to`、`source_url`（檢索後能溯源）

### R4：RAG 查詢 API

- Given ChromaDB 已建庫、LLM 可用
- When `POST /query` body `{"question": "去好市多刷哪張卡最划算"}`
- Then 回 200，`answer` 為中文回答、`sources` 為 ≥ 1 筆 `{title, source_url, valid_to}`
- Then 已過期優惠（`valid_to` < 今天）不得出現在 sources 與 answer 中

### R5：查無資料時不幻覺

- When 問題與庫內資料無關（例：「火星旅遊有什麼優惠」）
- Then `answer` 明確表示「目前資料庫沒有相關優惠」、`sources` 為 `[]`；不得編造不存在的優惠

### R6：LLM 供應商切換

- Given 環境變數 `LLM_PROVIDER=ollama`（預設）或 `openai`
- Then 兩種設定下 R4 均通過
- Given `LLM_PROVIDER=openai` 但未設 `OPENAI_API_KEY`
- Then 服務啟動時立即失敗並輸出明確錯誤訊息（fail fast，不是查詢時才炸）

### R7：Telegram Bot

- When 使用者傳文字訊息給 Bot
- Then Bot 呼叫 `POST /query` 並回傳 answer + 來源連結
- When 使用者傳 `/start`
- Then 回覆使用說明（能問什麼、資料涵蓋範圍、資料更新日）

## 介面契約

### SQLite `offers` 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| source_type | TEXT | `credit_card` / `e_payment` |
| bank / provider | TEXT | 國泰、LINE Pay… |
| title | TEXT NOT NULL | 優惠標題 |
| content | TEXT NOT NULL | 優惠全文 |
| channel | TEXT | 適用通路（好市多、超商…） |
| reward_rate | TEXT | 回饋描述（原文保留，不強制解析成數字） |
| valid_from / valid_to | DATE nullable | 效期 |
| source_url | TEXT NOT NULL | 來源頁 |
| scraped_at | DATETIME NOT NULL | 爬取時間 |

### API（FastAPI + Pydantic）

```
POST /query
Request:  {"question": str}          # 1–500 字
Response: {"answer": str, "sources": [{"title": str, "source_url": str, "valid_to": str|null}]}
GET /health → {"status": "ok", "offers_count": int, "last_ingest_at": str|null}
```

## 具體範例（輸入 → 輸出）

1. `{"question": "去好市多刷哪張卡最划算"}` → answer 比較庫內含「好市多／Costco」通路的卡片優惠並給結論，sources 列出對應優惠頁連結
2. `{"question": "便利商店有什麼行動支付優惠"}` → answer 彙整 LINE Pay／街口的超商通路優惠，sources ≥ 1
3. `{"question": "火星旅遊有什麼優惠"}` → `{"answer": "目前資料庫沒有相關優惠資訊。", "sources": []}`

## 邊界情況與錯誤行為

- 空 body / 缺 `question` / question 超過 500 字 → 422（FastAPI validation error）
- 目標網站改版導致某來源爬取失敗 → 該來源 log ERROR、**既有資料保留不清空**、程式以非 0 exit code 結束（其他來源繼續爬完）
- LLM 逾時（> 90s；放寬自 30s 以涵蓋 8B 冷載入 ~24s 最壞情況，transport 層 120s 為外層上界）→ 504 `{"error": "LLM 回應逾時，請稍後再試"}`
- ChromaDB 尚未建庫 → `/query` 回 503 `{"error": "知識庫尚未建立"}`
- Telegram 收到非文字訊息（貼圖、圖片）→ 回覆「請用文字提問」

## 技術約束（本專案特有）

- 技術棧鎖定：Python + FastAPI、ChromaDB、sentence-transformers（須支援中文的 multilingual 模型）、Ollama 預設／OpenAI 可切換、SQLite、Telegram Bot
- 爬蟲禮儀：遵守 robots.txt、自訂 User-Agent、請求間隔 ≥ 1 秒
- `reward_rate` 保留原文不解析——回饋規則太雜，解析錯比不解析糟

## 分階段任務清單

- [ ] F1：資料模型 + SQLite schema（驗證：pytest 過、可插入/查詢 offer）
- [ ] F2：信用卡爬蟲 ×3 家（驗證：R1）
- [ ] F3：chunker + embedder + ChromaDB ingest（驗證：R3）
- [ ] F4：RAG pipeline，CLI 可問答（驗證：CLI 跑範例 1 有合理回答）
- [ ] F5：FastAPI `/query` + `/health`（驗證：R4、R5、Swagger 可測）
- [ ] F6：Telegram Bot 串接（驗證：R7）
- [ ] F7：電子支付爬蟲 ×2 家（驗證：R2）
- [ ] F8：OpenAI 切換支援（驗證：R6）
- [ ] F9：README + `.env.example`，clone 後照文件可跑起（驗證：乾淨環境走一遍）

## 完成定義（必過的指令）

- `pytest` 全過，覆蓋率 ≥ 80%
- `ruff check .` 無錯誤
- 三個具體範例問題手動驗證通過（Telegram 端）

## 開放問題

- [x] 三家銀行最終名單：國泰、台新、富邦（2026/07/10 定案，見 R1 註記；玉山列入未來可加項，需 Playwright）
- [ ] 資料更新頻率與排程化——MVP 後決定（決策人：Ryan）
