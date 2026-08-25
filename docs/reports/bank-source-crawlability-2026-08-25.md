# 台灣發卡行優惠頁可爬性盤點

> 2026-08-25，20 家全數實測（每家最多 3 個候選網址，總請求約 40 次）。
> 已在專案內的跳過：國泰、台北富邦、台新、icash Pay、街口。

| 機構 | 優惠頁 | 判定 | 證據摘要 |
|---|---|---|---|
| 星展 | dbs.com.tw/personal-zh/cards/cards-offers/default.page | 靜態可爬 | 200/407KB，含「台灣虎航全航線購票最優88折」 |
| 凱基 | kgibank.com.tw/zh-tw/personal/promotion/card-campaign | 靜態可爬 | 200/520KB，含「7-11/全家/全聯最高10%回饋」 |
| 永豐 | bank.sinopac.com/sinopacBT/personal/credit-card/discount/list.html | 靜態可爬 | 200/77KB，含「Apple Pay 感應進站最高100%刷卡金」 |
| 滙豐 | shop.hsbc.com.tw | 靜態可爬 | 200/52KB，含「滿2,000元現折」 |
| 樂天 | card.rakuten.com.tw/corp/campaign/ | 靜態可爬 | 200/194KB，優惠標題直接在 HTML |
| 新光 | skbank.com.tw/CCO_1.html | 靜態可爬 | 200/703KB，含活動連結與回饋文字 |
| 上海商銀 | scsb.com.tw/content/card/discountShopList | 靜態可爬 | 200/78KB，含「訂房9折」「餐飲9折」 |
| 將來 | nextbank.com.tw/announcement/... | 靜態可爬 | Next.js SSR，HTML 含「將將卡最高5%N點」 |
| 悠遊卡/悠遊付 | easycard.com.tw/offers | 靜態可爬 | 200/61KB，商店名在 alt 屬性，細節在內頁 |
| 王道 | o-bank.com/retail/event/event-announce | 靜態（密度低） | 混雜換匯/公告，信用卡優惠占比低 |
| 華南 | hncb.com.tw/wps/portal/HNCB/card/benefit | 靜態（密度低） | 只有固定權益分類；檔期活動頁是 JS 表單 |
| 兆豐 | megabank.com.tw/personal/credit-card | API 可爬 | 主頁 SSR 有內容；`/api/client/DiscountOverview/GetDiscount` POST 通但回空，需摸參數 |
| 玉山 | esunbank.com/.../discount/shops/all | API 可爬（有阻擋） | 殼＋`DiscountSearchResult` API，直打被 302 轉 rpcd 驗證 |
| 遠東商銀 | feib.com.tw/activity?id=NNNN | 部分靜態 | 單頁靜態全文；彙整清單 404、登錄站有 captcha，無法枚舉 id |
| 全支付 | marketing.pxpayplus.com/pxplus_marketing_page/* | 部分靜態 | 活動單頁靜態；官網清單是 Vue 殼 |
| 合作金庫 | tcb-bank.com.tw/.../discount/event | 需瀏覽器 | 檔期活動連結 JS 載入 |
| 聯邦 | card.ubot.com.tw/CardActivity | 需瀏覽器 | 1.5KB Vue 殼，app.js 無 API 路徑 |
| LINE Bank | linebank.com.tw/notice/events | 需瀏覽器 | SPA 殼＋嚴格 CSP，無可直打 API |
| 第一銀行 | card.firstbank.com.tw/sites/card/CardIndex | 需瀏覽器 | 403 WAF（換 UA/headers 皆拒） |
| 中國信託 | ctbcbank.com/.../inx_cc_offer.html | 需瀏覽器 | HTTP 202 混淆 JS 反爬挑戰頁 |

## 建議優先序

1. **星展、凱基、永豐**——靜態、單頁密度最高（標題直接含回饋數字）
2. **樂天、滙豐、新光、上海商銀**——靜態、密度中等、結構單純
3. **將來、悠遊卡**——靜態但格式特殊，需客製 parser
4. **兆豐**——API POST 已通，值得摸參數；玉山要先解 rpcd 阻擋
5. **王道、華南**——密度低，性價比差
6. 遠銀、全支付、合庫＋純瀏覽器組（聯邦、LINE Bank、一銀、中信）——要做就用 Playwright 批次一起處理

## 決策脈絡

同日 idea-reality 報告結論：差異化在技術形狀不在覆蓋率，來源以「足夠展示多來源架構」為上限。
故此表是候選池不是待辦清單——F23（自癒式爬蟲）上線後再從第 1 檔挑，每次加 1-2 家即可。
