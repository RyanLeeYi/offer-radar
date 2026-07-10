# Session Handoff

> 最後更新：2026-07-10 23:05

## 這個 session 做了（F4）

- **F4 passing**：RAG pipeline + CLI `python -m rag.query "問題"`。PRD 三範例實測全過（好市多→Costco聯名卡2%、便利商店行動支付→4優惠帶引用、火星→拒答且無來源）
  - `rag/retriever.py` **混合檢索**：中文 n-gram + 英數字詞（`rag/keywords.py`）經 `$contains` 精確匹配（命中標 keyword_match 免距離門檻）+ bge-m3 向量 top20，合併去重
  - `rag/generator.py` Ollama qwen3:8b：**prompt 配方見 DECISIONS D6**（不用 system role、指令置尾、think:false、num_ctx 8192）——換模型時要重驗
  - `rag/pipeline.py`：門檻 0.4 sanity + 一優惠留最佳 chunk + context cap 12 + sources cap 5 + R5 雙防線（無 hits 直接拒答不呼叫 LLM；LLM 拒答則清 sources）
  - **順手修了 F2 富邦解析器**：側欄 swiper/頁尾雜訊混入 content 毒化檢索（fixture: fubon_detail_sidebar.html），已重爬重建（228 優惠 → 1531 chunks）
  - embedding 換 BAAI/bge-m3（MiniLM/e5-small 實測鑑別度不足，D6）；93 tests、ruff clean

## 做到一半 / 已知未修

- 無半成品。已知限制：
  1. `$contains` 全文掃描 ~30 次/查詢，語料破萬或 API 高並發時換 FTS 索引（D6 代價欄）
  2. F2 遺留：台新/富邦 load-more 覆蓋率缺口、robots 程式化檢查（前 session 記錄）
  3. 本機 `.env` 設 `OLLAMA_MODEL=qwen3:8b`（config 預設仍 llama3.1:8b，F8/F9 時統一檢討）；`.env.example` 尚未列 `EMBEDDING_MODEL`
- Ollama 服務要手動起（`ollama serve`），qwen3:8b 冷載入 ~24 秒

## 下一步（具體到可直接動手）

1. F5 FastAPI `/query` + `/health`（api/ 只呼叫 `rag/pipeline.py`，不直接碰 ChromaDB/SQLite）
2. 驗收 R4+R5：200 帶 answer+sources；無關問題固定句+空 sources（pipeline 已保證）；缺 question/超 500 字→422；未建庫→503；LLM 逾時 30s→504（**這層契約在 API 做**，transport 層是 120s）
3. `/health` 回 `{status, offers_count, last_ingest_at}`——last_ingest_at 目前沒存，ingest 時寫進 chroma collection metadata 或 SQLite 一張 meta 表
4. 測試用 httpx TestClient + 假 pipeline 注入；Swagger 手動驗證一輪
