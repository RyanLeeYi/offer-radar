# Session Handoff

> 最後更新：2026-08-25

## 這個 session 做了

1. **F16 Telegram 真機驗證補做**：查詢中提示→就地 edit、逾時訊息、F15 拒答句＋miss_log 寫入皆實測通過（Claude in Chrome 操作 Telegram Web）。順手清掉重複跑的第二份 bot 進程（會互搶 getUpdates）。
2. **F17–F19 三路平行派工收官**（各自 worktree，每條 5–8 分鐘）：
   - F17 LLM 呼叫層合流：新增 `rag/llm_provider.py` 單一定義 THINK_TAG／TIMEOUT／select_provider
   - F18 設定收斂:`OFFER_RADAR_DB` 單軌（validation_alias）、`QUERY_TIMEOUT_SECONDS` 契約常數收進 `config/settings.py`，bot=契約+5 導出
   - F19 backfill 去重改吃 `search_log` 表的實際搜尋時間，不受讀取 limit 影響
3. **F21 PTT 省錢版資料源收官**：`scraper/sources/lifeismoney.py`（純爬取，over18 cookie）＋ `rag/ptt_extractor.py`（LLM 抽取）＋ `rag/ptt_ingest.py`（組裝入口，`python -m rag.ptt_ingest`）。驗收者獨立重跑真實一頁 fetched=14 stored=3，F14 警語路徑獨立重現。
   - 派工教訓：第一輪 worker 正確停下——acceptance 要求重用 rag/llm.py 但 touches 沒給 rag/ 檔案，與「scraper 不得 import rag」衝突；修 touches（scope_note 記錄）後續作成功。acceptance 原文全程未動。
4. 四條全部 fresh-context 逐條驗收後 passing 並歸檔（F17/F18/F19 各 6/6、F21 11/11）。

## 2026-08-25 下半場追記

5. **F22（iPASS MONEY 官方資料源）passing 歸檔**：`scraper/sources/ipassmoney.py`＋`rag/ipass_extractor.py`＋`rag/ipass_ingest.py`（`python -m rag.ipass_ingest`），真實跑一頁 fetched=10 stored=9、全 verified 不帶警語。
6. **F23（自癒式爬蟲）passing 歸檔**：解析失敗（例外／0 筆）→ 存證 `data/failed_pages/`＋警告；`python -m rag.selfheal` 消化存證區、LLM 抽取入庫標 `llm_fallback` tier＋專屬警語；修復迴圈文件 `docs/self-heal-fixture-loop.md`。首輪驗收抓到 cathay 未涵蓋（P2），修復後針對性重驗解除。
7. **兩份調查報告**進 `docs/reports/`：idea-reality（開源空白／商業紅海，維持作品集定位）、20 家發卡行可爬性盤點（候選池：星展／凱基／永豐最優）。

## 2026-08-25 晚場追記

8. **F24（claude 訂閱制 provider）passing 歸檔**：`LLM_PROVIDER=claude` 時 generator 與 rag 側抽取全走
   subprocess `claude -p`（吃 Claude 訂閱額度、不需 API key）；三 provider 共用 F17 的 select_provider。
   驗收者獨立真打四輪（48-59 秒回答案＋來源），其中一輪 claude 判資料不足觸發拒答句——真實 LLM 變異，
   要當生產 provider 用時留意體感。ollama 仍為預設。

## 2026-08-25 深夜追記（無人看管 session：F20 未動工）

9. **F20 依然無法執行，且今晚多出一個獨立阻塞**。已投兩筆 question 進 brief-me 收件匣待裁決。
   - **阻塞一（原有）**：`.env` 與環境變數都沒有 `OPENAI_API_KEY`。實測 `LLM_PROVIDER=openai`
     起 `select_provider()` 照設計 fail fast。金鑰要花錢，只有 Ryan 能決定 → 沒有動工。
   - **阻塞二（新發現）**：acceptance 最後一步「切回 ollama 並確認 /query 仍正常」目前也過不了。
     `POST /query` 空等滿 90 秒（`QUERY_TIMEOUT_SECONDS`）回 504；直接打 ollama
     `/api/generate`（「說好一個字」、`num_predict=16`）190 秒仍無回應。
   - **阻塞二的根因在主機不在 repo**：`ollama ps` 顯示 qwen3:8b 被排成 `94%/6% CPU/GPU`，
     主機可用 RAM 只剩 **643MB / 16GB**（Memory Compression 1.5GB＋qemu/Docker＋vmmemWSL＋
     Chrome＋防毒＋今晚多個併發 claude session）。RTX 3050 僅 8GB VRAM、已用 1.6GB，
     塞不下 6GB 模型＋KV cache 才退回 CPU，再撞 RAM 耗盡而 thrash。
     **刻意沒改 `OLLAMA_MODEL`**：`.env.example` 明寫 prompt 配方是針對 qwen3:8b 調的、換模型要重驗。
   - **下次要驗 ollama 前先看這個**：`ollama ps` 的 PROCESSOR 欄。出現 `%CPU` 佔多數就是這個坑，
     先關掉 Docker/WSL/其他 session 再驗，不要浪費時間往 repo 裡找 bug。

### 這次 session 有查證的事實（給下一個 agent 省時間）

- `uv run pytest -q` → **309 passed**（27.76s），與上一份 handoff 一致
- API `/health` → 200；openai SDK 已裝（2.44.0）；`OPENAI_MODEL` 預設 `gpt-4o-mini`
- 結論：**金鑰一到，F20 可以一次跑完**——除了金鑰，其他前置條件都已就緒（但 ollama 那步要等主機不忙）

## 目前狀態

- 309 tests／90% coverage／ruff clean，HEAD 與 origin 同步（800afca）
- `feature_list.json` 只剩 **F20**（openai 真 API 驗證），blocked：需要 Ryan 提供 `OPENAI_API_KEY`（會產生費用）；openai 分支依 Ryan 裁決保留
- **08/25 深夜補**：ollama 目前在本機跑不動（RAM 耗盡 → CPU 退回 → thrash），詳見下方深夜追記
- PTT 資料源**尚未掛進 `scraper/runner.py` 正式排程**——跑批走 `python -m rag.ptt_ingest`（刻意留到有需要再接線）
- PTT offer 刻意不設 TTL（`expires_at=None`），理由見 `rag/ptt_extractor.py` docstring
- Tavily 補查仍刻意關閉（Ryan 08/23 裁決）；拒答句「稍後補查」DEFER 條件不變

## 下一步

1. F20：Ryan 填 `OPENAI_API_KEY` 後照 acceptance 跑一次真 API 驗證。
   **開跑前先 `ollama ps` 確認不是 `%CPU` 佔多數**——acceptance 最後一步要切回 ollama 驗 `/query`，
   主機忙的時候那步必失敗（見深夜追記）
2. 想讓 PTT 定期入庫：把 `rag/ptt_ingest` 掛排程或接進 runner（開新 feature）
3. bot／API 已在 08/25 重啟至現行 code；PTT 新資料要入正式庫需手動跑一次 `uv run python -m rag.ptt_ingest`

## 啟動順序（不變）

`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`
