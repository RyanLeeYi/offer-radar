# Session Handoff

> 最後更新：2026-07-10 17:00

## 這個 session 做了（F3）

- **F3 passing**：chunker + embedder + ChromaDB ingest（`python -m rag.ingest`）
  - `rag/chunker.py` 段落優先切塊、上限 450 字、超長硬切不掉字；`rag/embedder.py` sentence-transformers 薄封裝（延遲載入）；`rag/vector_store.py` ChromaDB 唯一入口（rebuild→upsert 全量重建）；`rag/ingest.py` 讀未過期優惠→切塊→embedding→入庫
  - 實跑真資料：228 筆未過期（total 243）→ 1543 chunks；ChromaDB distinct offer_id=228 對齊 SQLite active；metadata 含 offer_id/valid_to/source_url/title
  - embedding=paraphrase-multilingual-MiniLM-L12-v2（D5）；64 tests passed、ruff clean；code-review 無高信心問題
  - 新增 `scraper/db.py::list_active_offers`（valid_to null 或 ≥ today）

## 前一個 session 做了（F2）

- **F2 passing**：信用卡爬蟲 ×3 家。動工前偵察發現中信全站反爬（混淆 JS 挑戰頁）、玉山列表 API 被 WAF 擋非瀏覽器請求 → 問過 Ryan 後名單改為**國泰＋台新＋富邦**（vault DECISIONS.md D4、PRD R1 註記）
  - 國泰：cathay-cube sitemap（114 個活動頁）+ AEM `.model.json` 結構化 API
  - 台新：mkpcard CMS 分類列表（A–I）+ 明細靜態頁；富邦：cardpromote 分類（A–F）+ 明細靜態頁，兩家共用 `sources/_shared.py` 管線
  - 實跑 3 輪：243 筆（110/97/36）、重跑不重複、exit 0；47 tests、coverage 95%、ruff clean
- code review 7 findings 修 5：單頁 HTTP 錯誤隔離（不再一頁拖垮整來源）、跨年簡寫效期進位（12/15-1/15）、upsert 改 caller 控 transaction（一來源一 commit，順手清了 F1 技術債）、台新/富邦重複管線抽共用、國泰內文照 `:itemsOrder` 排序

## 做到一半 / 已知未修

- 無半成品。code review 遺留 2 筆（都不擋驗收）：
  1. **覆蓋率缺口**：台新/富邦只抓得到列表頁靜態渲染的第一批（load-more AJAX 被 WAF 擋）；國泰有 4 個圖片式活動頁抽不到內文、WARNING 跳過
  2. **robots.txt 靠人工確認**（三站 2026/07/10 均允許：cathay-cube 僅擋特定參數、mkpcard 無 robots、cardpromote 全允許），程式內沒有 robotparser 持續檢查
- 玉山日後要加需 Playwright headless（WAF 疑 TLS 指紋擋 curl/requests）——相關構想「自癒式爬蟲 LLM fallback」記在 vault `projects/backlog/點子.md`
- 爬蟲禮儀已實作：`scraper/http.py` PoliteClient（自報身分 UA + 間隔 ≥1 秒），全程 injectable 供測試

## 下一步（具體到可直接動手）

1. F4 RAG pipeline（CLI 可問答）：retriever（查 ChromaDB top-k）+ generator（Ollama，帶 source citation 防幻覺）+ pipeline 串接 → CLI `python -m rag.query "問題"`
2. 驗收：CLI 跑「去好市多刷哪張卡最划算」回中文答案 + ≥1 筆來源；過期優惠不出現（已在 F3 的 ingest 層擋掉，retriever 直接查庫即可）
3. 邊界：ChromaDB 只能經 `rag/vector_store.py`（需加 query 方法）；LLM 走 Ollama（`config.settings` 已有 ollama_base_url/model）；F8 再加 OpenAI 切換
4. 資料現況：`data/chroma` 已建好 1543 chunks 可直接檢索；重跑 `python -m rag.ingest` 可全量刷新
