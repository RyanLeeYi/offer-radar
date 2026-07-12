# 查無時 AI 網搜補資料（web_unverified 層）— 設計文件

> 日期：2026-07-12 · 狀態：設計核可，**觀察期（至 ~2026-07-25）結束後動工**
> 對應 features：F11–F15（feature_list.json，全標 failing）

## 背景與問題

MVP 來源涵蓋 3 銀行 + 2 電支，查詢 miss 率預期不低。原構想：查無時先回「查無」，背景由 AI 網搜補資料寫回資料庫，下次同類查詢就搜得到。

核心矛盾：專案的立身之本是防幻覺——「回答只根據實際入庫的優惠、每個結論都標來源」。未驗證的網搜結果直接混進 verified 資料會毀掉這個保證。

## 已定決策

| 決策 | 選擇 | 理由 |
|------|------|------|
| 信任模型 | **分層標示**：網搜結果進獨立 `web_unverified` 層，帶 TTL，回答時明確標示 | 補涵蓋率但不污染可信層 |
| 時機與回報 | **非同步、不推播**：先回查無，背景補完，下次再問才搜得到 | 實作最簡；推播列為未來可加 |
| 搜尋實作 | **Tavily API + 既有 LLM 抽取**（路線 A） | 免費額度 1000 次/月；內容乾淨利於抽取；搜尋與抽取分兩步，抽取失敗可只丟棄不入庫。備選：Brave Search API |
| TTL | 預設 **7 天** 到期自動失效 | 優惠變動快，寧可重搜不留舊資料 |

否決的路線：LLM 內建網搜（綁死單一雲端供應商、違背 local-first 與供應商切換敘事）；自架 SearXNG（對補救路徑而言維運太重）。

## 資料模型

`offers` 表加兩欄（現有五個爬蟲來源不動，寫入自動標 verified、不設 TTL）：

- `trust_tier`: `verified` | `web_unverified`
- `expires_at`: TTL 到期時間（僅 web_unverified 使用）

新增 `miss_log` 表：查無的 query 原文 + 時間戳。用途：①防重複搜（24h 內同 query 不重搜）②需求數據，決定下一個正式爬蟲寫誰。

ChromaDB chunk metadata 同步帶 `trust_tier`；ingest 時清掉已過期的 web_unverified chunk。

## 流程

```
使用者問 → RAG 檢索 → 查無
  → 回覆「目前資料庫沒有相關資訊，已記下這個問題、稍後補查」
  → 寫 miss_log
  → 背景 job：
      24h 內同 query 已搜過 → 跳過
      → Tavily 搜尋（include_domains 優先官網網域）
      → LLM 結構化抽取（獨立 prompt，輸出過 Pydantic schema 驗證）
      → 必要欄位齊全才寫入（trust_tier=web_unverified, expires_at=+7d）
      → rag.ingest 進 ChromaDB
```

## 回答標示（分層信任的落地點，不可省）

引用 `web_unverified` 資料的結論必須附加：「⚠️ 來自網路搜尋、未經驗證，使用前請確認官網」。全部來自 verified 時行為與現狀相同。

## 安全防線

1. **網搜內容視為不可信輸入**：只進抽取用獨立 prompt；抽取輸出以 Pydantic schema 驗證，不合格整筆丟棄（防 prompt injection 與垃圾資料）
2. **抽不出必要欄位不入庫**：沿用爬蟲原則（解析不出就丟，不回空殼）
3. **Tavily API key 進 `.env`**，不硬編碼
4. **防額度濫用**：miss_log 24h 去重

## Feature 拆分（實作順序）

| ID | 內容 | 依賴 |
|----|------|------|
| F11 | miss_log 記錄與 24h 防重複 | 無（先做，觀察期數據也用得上） |
| F12 | trust_tier + expires_at + 過期清理 | 無 |
| F13 | Tavily 搜尋 + LLM 抽取 pipeline（抽取失敗不入庫） | F12 |
| F14 | 回答標示 unverified 警語 | F12 |
| F15 | 背景 job 端到端串接 | F11–F14 |

## 邊界與不做的事

- 不做完成推播（bot 維持被動回覆；未來可加）
- 不做查詢時同步等待網搜
- 不做 web_unverified → verified 的自動升級（該通路需求高就寫正式爬蟲，見 miss_log 數據）
