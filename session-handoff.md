# Session Handoff

> 最後更新：2026-07-10 16:10

## 這個 session 做了

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

1. F3 chunker + embedder + ChromaDB ingest（`python -m rag.ingest`）
2. 驗收 = PRD R3：ChromaDB 筆數 = SQLite 未過期筆數（`valid_to` null 或 ≥ 今天）；每 chunk metadata 含 `offer_id`/`valid_to`/`source_url`
3. 注意邊界：ChromaDB 只能經 `rag/vector_store.py` 操作（CLAUDE.md）；embedding 模型要選支援中文的 multilingual（sentence-transformers 已在依賴）
4. 資料現況：`data/offers.db` 243 筆可直接餵；26 筆 valid_to 為 null（屬合法）、其餘有效期，過期過濾邏輯 F3 實作
