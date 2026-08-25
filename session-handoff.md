# Session Handoff

> 最後更新：2026-08-23（無人看管 session，由 agent-brief-me 派出）

## 這個 session 做了：消化 Tavily 裁決，沒有動程式碼

inbox 答覆（`52fd8b1d`）：**「先不申請——補查功能暫時關著，等之後真的想用再說」**。

這條決定要求的狀態，**repo 已經在上面了**，所以本輪沒有實作，只做查證與記錄。

### 查證過的三件事（不是推論，是跑出來的）

1. **缺 key 只關掉補查，不影響任何前台功能**——`config/settings.py:16` 的
   `tavily_api_key: str = ""` 有預設值，`build_search` 只在 `rag/backfill.py:150` 的
   `main()` 內部 lazy import 呼叫。api／bot／pipeline 完全碰不到它，啟動與查詢照常
2. **`uv run python -m rag.backfill` 在 3.8 秒內退出**，訊息是
   `ValueError: TAVILY_API_KEY 未設定，請在 .env 填入後再啟動（免費額度 1000 次/月）`。
   原本擔心它會先載完 torch 才報錯（`from rag.embedder import Embedder` 排在 `build_search` 之前），
   實測沒有——`rag/embedder.py` 自己也是延後載入。**這個「關著」的狀態是乾淨的，不用另外加開關**
3. **242 tests pass、ruff clean**（baseline，本輪未改任何 `.py`）

唯一的程式碼變更是 `.env.example` 第 16 行起的註解：把「留空」寫成**刻意的預設狀態**，
不是待辦事項。否則下一個 agent 看到空 key 又會投一次 question 問要不要申請。

## 已知不一致（DEFER，附觸發條件）

**拒答句仍然承諾「稍後補查」，但補查不會發生。**
`rag/pipeline.py:18` 的 `NO_RESULT_ANSWER = "目前資料庫沒有相關優惠資訊。已記下這個問題、稍後補查。"`

- 「已記下這個問題」是**真的**——F11 的 miss_log 照常寫入，key 到位後那些 miss 補得回來
- 「稍後補查」目前是空頭支票
- **沒有直接改掉它**：F15 的 frozen acceptance 逐字要求「回覆含『已記下這個問題、稍後補查』」，
  而 F15 已 passing 並歸檔。改字＝讓一條已通過的 feature 失效，要走取代流程（開新條目、
  舊條目原文不動加 `superseded_by`）並重新簽核——為一句暫時性的措辭燒一條 feature 不划算
- **重新評估的觸發條件**：(a) 決定長期不開補查（那就正式取代 F15 的那條 acceptance），
  或 (b) bot 開始有 Ryan 以外的使用者。key 補上就自動一致，什麼都不用改

## 目前狀態

- `feature_list.json` 的 features **是空的**——F1–F15 全部 passing 並歸檔在
  `docs/archive/features.jsonl`。下一條 feature 要自己開，開了要簽核才能動工
- 242 tests／ruff clean／coverage 88%
- 補查功能：**刻意關閉中**，不是壞掉

## 下一步（沒有一項在等 inbox）

1. **要繼續推進就得先開 feature**——目前沒有 failing 條目可接。候選見下方技術債
2. bot／API 若還跑著舊版，重啟才吃得到 F14 警語與新拒答句
3. 技術債（前幾輪 DEFER，都還沒開條目）：
   - `rag/llm.py` 與 `rag/generator.py` 的 provider 選擇／think 剝除／timeout 重複一份
     （當初為讓 worker 與主 session 檔案不重疊而分開，可合流）
   - 24h 去重用 miss 的 `created_at` 近似「搜過的時間」，被 limit 擋在窗外的 miss 可能提早重搜
   - DB 路徑雙軌（`OFFER_RADAR_DB` vs `DATABASE_PATH`）
   - bot 95s／api 90s 逾時常數散在兩處
   - `LLM_PROVIDER=openai` 真 API 從沒手動驗過（F16 Telegram 真機驗 edit 已於 2026-08-25 補做：
     查詢中提示→就地 edit 成答案／逾時訊息、F15 拒答句＋miss_log 寫入皆實測通過；
     第一發冷載入吃滿 90s 逾時屬預期，暖機後約 30s 回答）
4. 想開補查時：`.env` 填 `TAVILY_API_KEY` → `uv run python -m rag.backfill` →
   看 `requests=` 與 `stored=`，確認抽取 prompt 對真實網頁管用；不管用就調 `_EXTRACT_INSTRUCTIONS`

## 啟動順序（不變）

`ollama serve` → `uv run uvicorn api.main:app` → `uv run python -m bot.main`
