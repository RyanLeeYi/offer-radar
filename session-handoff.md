# Session Handoff

> 最後更新：2026-08-31（無人看管 session，agent-brief-me 派工）

## 目前狀態

- **321 passed / 1 failed / ruff clean**（那條 failed 是既有的，不是這場弄的，見下）
- `feature_list.json` 剩三條 failing：
  - **F20** openai 真 API 驗證（blocked：需要 Ryan 提供 `OPENAI_API_KEY`，會產生費用）
  - **F27** API_BASE_URL 改 127.0.0.1（**實作已完成並 commit，但驗收沒過**，見下）
  - **F28** 測試套件兩處腐爛（**新開、未簽核**，已投 sign-off 卡）
- 08/28 handoff 那條「待 Ryan 裁決：API_BASE_URL 要不要比照改」**已裁決並落地**（F27 實作面）

## 這個 session 做了

**F27 實作完成（commit `66d73f4`），但狀態維持 `failing`。** 來源是 Ryan 在 brief-me 對
question `cadc47f0` 與 `4ac18388` 的答案（兩筆是同一個決定，都選核准）。

改動與 F26 形狀一模一樣，只有預設值與註解，沒動任何呼叫路徑：

- `config/settings.py` 的 `api_base_url` 預設 → `http://127.0.0.1:8000`
- `.env.example` 的 `API_BASE_URL` 同步，並註明「API 在別台機器就填該位址」
- `tests/test_settings.py` 兩條斷言釘住：預設值是 127.0.0.1、且 `API_BASE_URL` 覆寫得回去
- `bot/` 零改動——它本來就讀 `settings.api_base_url`

**實測（真 socket，API 當時正跑在 8000 上）：`localhost` 2.620s vs `127.0.0.1` 0.001s。**
這 2.6 秒是 bot 每次呼叫 `/query` 都在白付的。

### 為什麼做完了還是 failing（下一個 agent 不要直接改成 passing）

F27 的 frozen acceptance 字面要求「`pytest` 全綠」。fresh-context `acceptance-verifier`
逐條判 **5/6 pass**，唯一 fail 的就是這條 R5，標 **P3 / Confidence high**：

`tests/test_backfill.py::test_end_to_end_miss_becomes_retrievable_with_warning` 是紅的，
但**與 F27 無因果關係**——主 session 與驗收者各自獨立確認：在基準 commit `8bb64c0` 上
同樣紅，且 `rag/ingest.py`／`scraper/db.py`／`tests/test_backfill.py` 三檔本次一個字都沒動。

處置：R5 判 **DEFER 到 F28**，F27 維持 `failing`。兩件事都沒做：
不改 frozen acceptance 讓它過，也不越過 `touches` 去動 `rag/ingest.py`——
那正是 F21／F23 踩過的坑（acceptance 與 touches 互斥時，正確動作是停下來把卡開好）。

**F28 核准 → 修好 → 重跑 pytest 全綠 → F27 只要重驗 R5 一條即可改 passing**（1-4、6 已判 pass）。

## F28 是什麼（根因都查完了，核准後直接動手）

兩個既有的測試基礎設施缺陷，都在基準 commit 上重現：

1. **時間炸彈**：`rag/ingest.py:35` 的 `ingest()` 收了 `today` 卻沒收 `now`，
   `scraper/db.py:172` 的 `now = now or datetime.now()` 於是 fallback 成真實系統時鐘。
   `valid_to` 用寫死的 `today` 過濾、`expires_at`（7 天 TTL）用真實時間過濾，**兩把尺不同步**。
   測試 `NOW = 2026-08-23` + 7 天 = 08-30 到期，所以 **2026-08-31 起必然紅**。
   修法：`ingest()` 加 `now: datetime | None = None` 透傳（預設 None，production 兩個呼叫點行為不變）。
2. **狀態洩漏**：`tests/test_settings.py::test_query_timeout_single_contract_constant` 在
   `finally` 裡 reload 兩個模組，但 monkeypatch 還原常數發生在 `finally` **之後**，
   於是模組留著 42.0/47.0 污染後續。實證：`uv run pytest tests/test_settings.py tests/test_bot.py`
   會紅在 `test_client_query_posts_question`（`assert 47.0 > 90`），整套按字母序跑則不會。
   修法：讓還原順序正確（reload 前先還原常數）。

## 委派判斷（baton-dispatch 五問）

**0 個 executor 派工。** Q2（直接做更快）單獨就否決了——F27 實際 diff 是 2 個預設值加 2 條測試，
派工單比 diff 長，worktree 還得從 `origin/main` 重建脈絡。驗收另派唯讀 `acceptance-verifier`（唯一一個派工）。

## 下一步

1. Ryan 核准 F28 → 修兩處 → `pytest` 全綠 → 回頭重驗 F27 的 R5 一條 → F27 改 `passing` 並歸檔
2. F20 仍等 `OPENAI_API_KEY`
