"""信用卡來源解析測試（F2）：全部用本地 fixture，不打真站。

fixture 來源（2026-07-10 實站存檔）：
- cathay_sitemap.xml / cathay_event.model.json：cathay-cube sitemap 與 AEM 內容 API
- taishin_offer_list.html / taishin_detail.html：mkpcard CMS 列表與明細
- fubon_category.html / fubon_detail.html：cardpromote 分類與明細
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from scraper.dates import parse_period
from scraper.sources import cathay, fubon, taishin

FIXTURES = Path(__file__).parent / "fixtures"
SCRAPED_AT = datetime(2026, 7, 10, 12, 0, 0)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParsePeriod:
    def test_full_range_with_spaces(self):
        assert parse_period("2026/07/08 ~ 2026/07/14") == (date(2026, 7, 8), date(2026, 7, 14))

    def test_full_range_no_spaces(self):
        assert parse_period("2026/07/02~2026/08/30") == (date(2026, 7, 2), date(2026, 8, 30))

    def test_end_without_year_inherits_start_year(self):
        assert parse_period("2026/7/1-9/30") == (date(2026, 7, 1), date(2026, 9, 30))

    def test_unparseable_returns_none_pair(self):
        assert parse_period("即日起至額滿為止") == (None, None)

    def test_cross_year_shorthand_bumps_end_year(self):
        # 跨年活動常見簡寫：迄日沒寫年、月份又小於起日 → 迄日進位到下一年
        assert parse_period("2026/12/15-1/15") == (date(2026, 12, 15), date(2027, 1, 15))

    def test_explicit_end_year_earlier_than_start_returns_none(self):
        # 兩邊都寫了年卻迄早於起 → 資料本身有問題，不猜
        assert parse_period("2026/12/15~2026/1/15") == (None, None)

    def test_embedded_in_longer_text(self):
        start, end = parse_period("活動期間：2026/7/8 00:00~2026/7/14 23:59 止")
        assert (start, end) == (date(2026, 7, 8), date(2026, 7, 14))


class TestParsePeriodNear:
    def test_window_boundary_does_not_truncate_end_date(self):
        """掃描窗口切在迄日數字中間時，不得拿截斷的日期當答案
        （2026/12/31 被切成 2026/12/3 → 優惠提早 28 天被當過期濾掉）。"""
        from scraper.dates import parse_period_near

        # marker(4) + 54 字填充 + 起日~迄日：窗口 80 字剛好切在迄日 2026/12/31 的最後一碼
        text = "活動期間" + "規" * 54 + "2026/07/01 ~ 2026/12/31"
        assert parse_period_near(text) == (date(2026, 7, 1), date(2026, 12, 31))

    def test_default_markers_include_common_variant(self):
        """「活動時間」是同義常見寫法：標記命中要優先於全文掃描，
        否則前面的點數到期樣板日期會被誤當效期（jkopay 修過的同款問題）。"""
        from scraper.dates import parse_period_near

        text = "紅利點數於2025/1/1~2025/12/31到期。活動時間：2026/7/1~7/31"
        assert parse_period_near(text) == (date(2026, 7, 1), date(2026, 7, 31))


class TestCathay:
    def test_list_event_urls_only_returns_individual_events(self):
        urls = cathay.list_event_urls(read_fixture("cathay_sitemap.xml"))
        # fixture 內 credit-card 三層路徑（分類/年月/活動代碼）共 114 條
        assert len(urls) == 114
        assert all("/event/overview/credit-card/" in u for u in urls)
        # 分類頁（一層）與年月列表頁（兩層）不得混入
        assert "https://www.cathay-cube.com.tw/cathaybk/personal/event/overview/credit-card/New" not in urls

    def test_parse_event_builds_offer(self):
        url = (
            "https://www.cathay-cube.com.tw/cathaybk/personal/event/overview/"
            "credit-card/shopping/202606/202607_7-11"
        )
        offer = cathay.parse_event(read_fixture("cathay_event.model.json"), url, SCRAPED_AT)
        assert offer.source_type == "credit_card"
        assert offer.bank == "國泰世華"
        assert "7-ELEVEN" in offer.title
        assert "｜" not in offer.title  # 站名字尾要去掉
        assert "1,111" in offer.content  # cub_textb 內文
        assert "<p>" not in offer.content  # HTML 要剝掉
        assert offer.valid_from == date(2026, 7, 8)
        assert offer.valid_to == date(2026, 7, 14)
        assert offer.source_url == url
        assert offer.scraped_at == SCRAPED_AT

    def test_fetch_walks_sitemap_then_events(self):
        sitemap = read_fixture("cathay_sitemap.xml")
        event_json = read_fixture("cathay_event.model.json")

        def fake_get(url: str) -> str:
            if url == cathay.SITEMAP_URL:
                return sitemap
            assert url.endswith(".model.json")
            return event_json

        offers = cathay.fetch(fake_get)
        assert len(offers) == 114
        assert all(o.bank == "國泰世華" for o in offers)

    def test_fetch_skips_page_on_http_error(self, caplog):
        """單頁暫時性 HTTP 錯誤只犧牲那一頁，不拖垮整個來源。"""
        import requests

        sitemap = read_fixture("cathay_sitemap.xml")
        event_json = read_fixture("cathay_event.model.json")
        broken_url = cathay.list_event_urls(sitemap)[0] + ".model.json"

        def flaky_get(url: str) -> str:
            if url == cathay.SITEMAP_URL:
                return sitemap
            if url == broken_url:
                raise requests.ConnectionError("connection reset")
            return event_json

        with caplog.at_level(logging.WARNING):
            offers = cathay.fetch(flaky_get)
        assert len(offers) == 113
        assert any("connection reset" in r.message or broken_url in r.message
                   for r in caplog.records)

    def test_parse_event_respects_items_order(self):
        """AEM :itemsOrder 與 dict 鍵序不同時，內文照 :itemsOrder 排。"""
        model = {
            "title": "測試活動｜國泰世華信用卡優惠活動",
            ":items": {
                "cub_textb": {"text": "<p>第二段內文</p>"},
                "cub_texta": {"text": "2026/07/01 ~ 2026/07/31"},
            },
            ":itemsOrder": ["cub_texta", "cub_textb"],
        }
        offer = cathay.parse_event(json.dumps(model), "https://example.com/x", SCRAPED_AT)
        assert offer.content.index("2026/07/01") < offer.content.index("第二段內文")


class TestTaishin:
    def test_list_detail_urls_absolute_and_unique(self):
        urls = taishin.list_detail_urls(read_fixture("taishin_offer_list.html"))
        assert len(urls) == len(set(urls))
        assert urls  # 至少一條
        assert all(u.startswith("https://mkpcard.taishinbank.com.tw/") for u in urls)
        assert all("/tscccms/promotion/detail/" in u for u in urls)

    def test_parse_detail_builds_offer(self):
        url = "https://mkpcard.taishinbank.com.tw/tscccms/promotion/detail/WM_20260212111219281"
        offer = taishin.parse_detail(read_fixture("taishin_detail.html"), url, SCRAPED_AT)
        assert offer.bank == "台新"
        assert "foodpanda" in offer.title
        assert "台新銀行" not in offer.title  # 「 ： 台新銀行」字尾要去掉
        assert offer.valid_from == date(2026, 7, 1)
        assert offer.valid_to == date(2026, 9, 30)
        assert "pandapro" in offer.content
        assert offer.source_url == url

    def test_fetch_walks_categories_then_details(self):
        list_html = read_fixture("taishin_offer_list.html")
        detail_html = read_fixture("taishin_detail.html")

        def fake_get(url: str) -> str:
            if "/promotion/offerList/" in url:
                return list_html
            assert "/promotion/detail/" in url
            return detail_html

        offers = taishin.fetch(fake_get)
        # 9 個分類會回同一份列表，明細去重後 = 列表內不重複連結數
        expected = len(taishin.list_detail_urls(list_html))
        assert len(offers) == expected
        assert all(o.bank == "台新" for o in offers)

    def test_fetch_skips_detail_on_http_error(self):
        import requests

        list_html = read_fixture("taishin_offer_list.html")
        detail_html = read_fixture("taishin_detail.html")
        urls = taishin.list_detail_urls(list_html)
        broken_url = urls[0]

        def flaky_get(url: str) -> str:
            if "/promotion/offerList/" in url:
                return list_html
            if url == broken_url:
                raise requests.HTTPError("503")
            return detail_html

        assert len(taishin.fetch(flaky_get)) == len(urls) - 1


class TestFubon:
    def test_list_detail_urls_absolute_and_unique(self):
        urls = fubon.list_detail_urls(read_fixture("fubon_category.html"))
        assert len(urls) == len(set(urls))
        assert urls
        assert all(
            u.startswith("https://cardpromote.taipeifubon.com.tw/promotion/Detail?sn=")
            for u in urls
        )

    def test_parse_detail_builds_offer(self):
        url = "https://cardpromote.taipeifubon.com.tw/promotion/Detail?sn=B000151"
        offer = fubon.parse_detail(read_fixture("fubon_detail.html"), url, SCRAPED_AT)
        assert offer.bank == "台北富邦"
        assert "別叫我成功" in offer.title
        assert "富邦信用卡 - " not in offer.title  # 站名字首要去掉
        assert offer.valid_from == date(2026, 7, 2)
        assert offer.valid_to == date(2026, 8, 30)
        assert "9折" in offer.content
        assert offer.source_url == url

    def test_fetch_walks_categories_then_details(self):
        category_html = read_fixture("fubon_category.html")
        detail_html = read_fixture("fubon_detail.html")

        def fake_get(url: str) -> str:
            if "Type?category=" in url:
                return category_html
            assert "Detail?sn=" in url
            return detail_html

        offers = fubon.fetch(fake_get)
        expected = len(fubon.list_detail_urls(category_html))
        assert len(offers) == expected
        assert all(o.bank == "台北富邦" for o in offers)

    def test_parse_detail_excludes_sidebar_and_footer_noise(self):
        """側欄促銷卡與頁尾雜訊不得混入 content——會毒化 RAG 檢索（F4 實測教訓）。"""
        url = "https://cardpromote.taipeifubon.com.tw/promotion/Detail?sn=D000275"
        offer = fubon.parse_detail(read_fixture("fubon_detail_sidebar.html"), url, SCRAPED_AT)
        assert "Costco聯名卡友專屬優惠" not in offer.content  # 側欄 swiper 卡片標題
        assert "優食好市多專區享2%回饋" not in offer.content  # 同上
        assert "24小時服務專線" not in offer.content  # 頁尾
        assert "©" not in offer.content
        assert offer.content  # 主內容還在

    def test_fetch_skips_detail_on_http_error(self):
        import requests

        category_html = read_fixture("fubon_category.html")
        detail_html = read_fixture("fubon_detail.html")
        urls = fubon.list_detail_urls(category_html)
        broken_url = urls[0]

        def flaky_get(url: str) -> str:
            if "Type?category=" in url:
                return category_html
            if url == broken_url:
                raise requests.HTTPError("503")
            return detail_html

        assert len(fubon.fetch(flaky_get)) == len(urls) - 1


class TestParserRejectsGarbage:
    """版面大改時解析器要炸出來，不是回空殼 Offer。"""

    def test_cathay_raises_on_json_without_title(self):
        with pytest.raises(ValueError):
            cathay.parse_event("{}", "https://example.com/x", SCRAPED_AT)

    def test_taishin_raises_on_blank_page(self):
        with pytest.raises(ValueError):
            taishin.parse_detail("<html></html>", "https://example.com/x", SCRAPED_AT)

    def test_fubon_raises_on_blank_page(self):
        with pytest.raises(ValueError):
            fubon.parse_detail("<html></html>", "https://example.com/x", SCRAPED_AT)
