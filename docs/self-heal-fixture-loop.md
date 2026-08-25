# 失敗頁自癒 + fixture 修復迴圈（F23）

兩條腿缺一不可：**腿一（fallback）**買時間——來源解析壞掉時，scraper 側把該頁原始
HTML 存進 `data/failed_pages/`（`.gitignore`，不進 git），`rag/selfheal.py` 用 LLM
補抽取入庫（`trust_tier=llm_fallback`），查詢引用時附警語。**腿二（fixture）**才是
根治：selector 終究要修好，fallback 只是不讓資料在修好之前完全消失。

## 存證區

`scraper/sources/_shared.py` 的 `fetch_listed_details`（台新／富邦／街口／icash Pay
共用）在兩種情況把該頁 HTML 存進 `data/failed_pages/`：

- `parse_error`：明細頁 `parse_detail` 擲例外（標題／內文抽不到）
- `zero_results`：列表頁抓取成功，但 `list_detail_urls` 解析出 0 筆連結

國泰世華（`scraper/sources/cathay.py`）走自己的抓取迴圈（sitemap，非分類列表頁），
不經 `fetch_listed_details`，但比照同一套規則各自呼叫 `archive_failed_page`：

- `parse_error`：活動頁 `parse_event` 擲例外
- `zero_results`：sitemap 抓取成功，但 `list_event_urls` 解析出 0 筆活動頁

檔名格式：`{來源}__{YYYYmmddTHHMMSS}__{reason}__{url-encoded 網址}.html`，內容是
未經加工的原始 HTML——可以直接複製成測試 fixture。

## 修復迴圈

1. 版面改版，某來源 selector 失效 -> `data/failed_pages/` 出現新檔
2. 複製該檔進 `tests/fixtures/`，依現有測試慣例（如
   `tests/test_credit_card_sources.py`）用它寫一條會紅的測試，斷言解析結果符合新版面
3. 修對應來源檔（`scraper/sources/*.py`）的 selector，直到新測試轉綠、既有測試仍綠
4. 確認 `rag/selfheal.py` 已經（或即將）用該存證頁補進資料庫的 fallback 資料不再需要
   ——selector 修好後下次爬蟲會抓到 `verified` 版本並覆蓋
5. 刪除 `data/failed_pages/` 下已經處理完的存證檔（`rag/selfheal.py` 不會自動刪除，
   見該檔 docstring）

## 為什麼不自動刪除存證頁

`rag/selfheal.py` 消化存證區只讀不寫（不刪除已處理的檔案）：存證頁本身就是「這裡
還有一個 selector 沒修」的證據，LLM fallback 抽取成功與否都不改變這件事仍待人工
處理。自動刪除會讓開發者失去線索，也會讓修復迴圈第 2 步失去 fixture 來源。
