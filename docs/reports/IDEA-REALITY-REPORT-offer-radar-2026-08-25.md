# Idea Reality Report — offer-radar

> 日期：2026-08-25。方法：gh CLI 搜 GitHub＋網頁搜尋（idea-reality MCP 未設定，人工實查）。
> 現實信號評分：**約 60/100**（商業紅海、開源空白）。

## 掃描結果

### GitHub（開源競品）：空白

搜「信用卡 優惠」「credit card taiwan bot」等，命中全為 0-1 星個人作：

| repo | 描述 | 星 | 更新 |
|---|---|---|---|
| stonebomdic/deal-radar | 台灣信用卡資訊爬蟲＋比較＋通路查詢（名字都撞） | 0 | 2026-02 |
| vigordiankong/credit-card-tracker | 台灣信用卡優惠追蹤器 | 0 | 2026-08-25 |
| YCM-WanTing/credit-card-query | 台灣信用卡優惠查詢系統 | 0 | 2026-08 |
| jimmyfu87/nccuapp | 電商爬蟲＋信用卡推薦 Android app | 1 | 2022 |

無成熟開源專案；「RAG＋Telegram bot＋多來源信任分層」組合零命中。

### 商業服務：紅海

- **iCard.AI**——最接近：AI 推薦比較信用卡／商家商品優惠，37 家銀行彙整
- **Cardli**（app）——450+ 卡資料庫，輸入商家推薦最高回饋卡
- 卡優新聞網、Money101、Roo.cash——人工彙整比較站（流量型老站）

## 判定：繼續，維持作品集定位

「查優惠」作為產品是紅海；作為**展示 AI 應用工程能力的作品**是空白區。差異化＝技術形狀，不是資料覆蓋率：

1. 本機 LLM＋向量檢索，零 API 成本（商業品做不到也不會開源）
2. 多來源信任分層（官方一手／UGC 網友回報／LLM fallback）＋查詢警語機制
3. 自癒式爬蟲（F23）——self-healing scraper with local LLM fallback，履歷亮點句
4. （潛在）MCP 介面讓任何 AI 助理接上——與 vault backlog「一卡通 AI 可發現性」互為鏡像

**不做**：與 iCard.AI 拚銀行覆蓋率；商業化。來源數量以「足夠展示多來源架構」為上限。

## 附：idea-reality MCP 設定（之後想用正式掃描時）

```bash
claude mcp add idea-reality --scope user -e GITHUB_TOKEN=$GITHUB_TOKEN -- uvx idea-reality-mcp
```
