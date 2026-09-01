# Session Handoff

> 最後更新：2026-09-01（無人看管 session，agent-brief-me 派工）

## 目前狀態

- **322 passed / 0 failed / ruff clean**（08-31 那條既有紅測試已由 F28 修掉）
- `feature_list.json` 只剩 **F20** 一條 failing，且是 blocked
- F27、F28 已 `passing` 並歸檔進 `docs/archive/features.jsonl`（累計 27 條）

## 唯一未完工作：F20

**F20 openai 真 API 手動驗證 — blocked，不是沒做，是起跑不了。**

acceptance 第一句就是「在 `.env` 設定 `OPENAI_API_KEY` 並切 `LLM_PROVIDER=openai` 後」，
而 `.env` 目前只有 `OLLAMA_MODEL` 與 `TELEGRAM_BOT_TOKEN`，**沒有金鑰**。
程式端是好的：`rag/llm_provider.py` 的 `select_provider` 對 openai 缺金鑰採 fail-fast，
`rag/llm.py:71` 與 `rag/generator.py:151` 兩條路徑都已接上。缺的只有金鑰本身。

已投 brief-me question `9fd85c5f`（三選項：Ryan 自己填金鑰／先擱著／收掉不做，建議「先擱著」）。
**下一個 agent 不要嘗試繞過**——這條是刻意的人工驗證，沒有金鑰就沒有東西可驗。

## 環境提醒

`uv run pytest` 現在對系統日期免疫（D14）。若日後又出現「昨天還綠、今天變紅」的測試，
第一個懷疑對象是某個讀時間的函式沒把 `now` 注入進去，不是功能壞掉。
