"""電子支付來源解析測試（F7）：全部用本地 fixture，不打真站。

fixture 來源（2026-07-11 實站存檔）：
- jkopay_newevent.html / jkopay_campaign.html：mkt.jkopay.com 活動總覽與 campaign 頁
  （Next.js RSC，內容在 self.__next_f flight payload）
- icashpay_list.html / icashpay_detail.html：icashpay.com.tw advertMessage 列表與明細
"""

import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from scraper.sources import icashpay, jkopay

FIXTURES = Path(__file__).parent / "fixtures"
SCRAPED_AT = datetime(2026, 7, 11, 12, 0, 0)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestJkopayList:
    def test_list_campaign_urls_absolute_and_unique(self):
        urls = jkopay.list_campaign_urls(read_fixture("jkopay_newevent.html"))
        assert len(urls) == len(set(urls))
        assert len(urls) == 19  # fixture 內 19 個 campaign（不含 newevent 自己）
        assert all(u.startswith("https://mkt.jkopay.com/zh-TW/campaign/") for u in urls)

    def test_list_campaign_urls_excludes_listing_page_itself(self):
        urls = jkopay.list_campaign_urls(read_fixture("jkopay_newevent.html"))
        assert "https://mkt.jkopay.com/zh-TW/campaign/newevent" not in urls

    def test_list_campaign_urls_ignores_asset_paths_on_other_hosts(self):
        """CDN 圖檔等他站路徑不得生出假 campaign（會對不存在的頁面丟請求）。"""
        html = '<img src="https://cdn.jkopay.com/campaign/banner.png">'
        assert jkopay.list_campaign_urls(html) == []


class TestJkopayParse:
    def test_parse_campaign_builds_offer(self):
        url = "https://mkt.jkopay.com/zh-TW/campaign/jkolunch"
        offer = jkopay.parse_campaign(read_fixture("jkopay_campaign.html"), url, SCRAPED_AT)
        assert offer.source_type == "e_payment"
        assert offer.provider == "街口"
        assert offer.bank is None
        assert "週三午餐主題日" in offer.title
        assert offer.title == offer.title.strip()
        assert offer.valid_from == date(2026, 7, 1)
        assert offer.valid_to == date(2026, 9, 30)
        assert "午餐券" in offer.content
        assert offer.source_url == url
        assert offer.scraped_at == SCRAPED_AT

    def test_parse_campaign_content_is_readable_text_not_payload(self):
        """content 要是人話，不是 RSC payload 原始碼。"""
        url = "https://mkt.jkopay.com/zh-TW/campaign/jkolunch"
        offer = jkopay.parse_campaign(read_fixture("jkopay_campaign.html"), url, SCRAPED_AT)
        assert "__next_f" not in offer.content
        assert "\\u" not in offer.content
        assert "self." not in offer.content
        assert "<" not in offer.content  # 不帶 HTML 標籤

    def test_parse_campaign_dedupes_repeated_payload_runs(self):
        """RSC payload 同段文字會重複出現，content 不得重複塞同一句。"""
        url = "https://mkt.jkopay.com/zh-TW/campaign/jkolunch"
        offer = jkopay.parse_campaign(read_fixture("jkopay_campaign.html"), url, SCRAPED_AT)
        lines = offer.content.splitlines()
        assert len(lines) == len(set(lines))

    def test_parse_campaign_ignores_boilerplate_dates(self):
        """街口幣到期說明的樣板日期（2025/1/1~2025/12/31）不得當成活動效期——
        會讓常青活動被 ingest 誤判過期。效期只信標題或「領券時間」等標記附近的日期。"""
        url = "https://mkt.jkopay.com/zh-TW/campaign/jkomemberday"
        offer = jkopay.parse_campaign(
            read_fixture("jkopay_campaign_evergreen.html"), url, SCRAPED_AT
        )
        assert offer.title == "街口 5 號會員日"
        assert offer.valid_from == date(2026, 7, 1)  # 領券時間：2026/7/1 - 7/5
        assert offer.valid_to == date(2026, 7, 5)

    def test_parse_campaign_keeps_fullwidth_tilde_period(self):
        """全形波浪號 ～ 是台灣促銷文案最常見的日期分隔符，不得切斷文字段——
        切斷會讓限時活動抽不到效期、永不過期地留在語料裡。"""
        html = (
            '<html><head><meta property="og:title" content="測試活動"/></head><body>'
            '<script>self.__next_f.push([1,"活動期間：2026/7/1～7/31 消費滿額回饋"])</script>'
            "</body></html>"
        )
        offer = jkopay.parse_campaign(html, "https://example.com/x", SCRAPED_AT)
        assert offer.valid_from == date(2026, 7, 1)
        assert offer.valid_to == date(2026, 7, 31)

    def test_parse_campaign_raises_on_blank_page(self):
        with pytest.raises(ValueError):
            jkopay.parse_campaign("<html></html>", "https://example.com/x", SCRAPED_AT)


class TestJkopayFetch:
    def test_fetch_walks_listing_then_campaigns(self):
        listing = read_fixture("jkopay_newevent.html")
        campaign = read_fixture("jkopay_campaign.html")

        def fake_get(url: str) -> str:
            if url == jkopay.LISTING_URL:
                return listing
            assert "/zh-TW/campaign/" in url
            return campaign

        offers = jkopay.fetch(fake_get)
        assert len(offers) == 19
        assert all(o.provider == "街口" for o in offers)

    def test_fetch_skips_campaign_on_http_error(self, caplog):
        import requests

        listing = read_fixture("jkopay_newevent.html")
        campaign = read_fixture("jkopay_campaign.html")
        broken_url = jkopay.list_campaign_urls(listing)[0]

        def flaky_get(url: str) -> str:
            if url == jkopay.LISTING_URL:
                return listing
            if url == broken_url:
                raise requests.HTTPError("503")
            return campaign

        with caplog.at_level(logging.WARNING):
            offers = jkopay.fetch(flaky_get)
        assert len(offers) == 18


class TestIcashpayList:
    def test_list_page_urls_covers_pagination(self):
        urls = icashpay.list_page_urls(read_fixture("icashpay_list.html"))
        assert len(urls) == len(set(urls))
        assert len(urls) == 6  # fixture 分頁 1–6
        assert all(
            u.startswith("https://www.icashpay.com.tw/advertMessage/index/page/") for u in urls
        )

    def test_list_detail_urls_only_internal_advert_pages(self):
        urls = icashpay.list_detail_urls(read_fixture("icashpay_list.html"))
        assert len(urls) == len(set(urls))
        assert len(urls) == 6
        assert all(
            u.startswith("https://www.icashpay.com.tw/advertMessage/view/id/") for u in urls
        )
        # 外連 icash.com.tw 的公告卡片不得混入
        assert not any("icash.com.tw/Home" in u for u in urls)


class TestIcashpayParse:
    def test_parse_detail_builds_offer(self):
        url = "https://www.icashpay.com.tw/advertMessage/view/id/2407"
        offer = icashpay.parse_detail(read_fixture("icashpay_detail.html"), url, SCRAPED_AT)
        assert offer.source_type == "e_payment"
        assert offer.provider == "icash Pay"
        assert offer.bank is None
        assert offer.title == "uniopen聯名卡icash2.0完成首次自動加值 搭北捷享7%回饋"
        assert offer.valid_from == date(2026, 7, 1)
        assert offer.valid_to == date(2026, 12, 31)
        assert "OPENPOINT" in offer.content
        assert offer.source_url == url
        assert offer.scraped_at == SCRAPED_AT

    def test_parse_detail_excludes_nav_noise(self):
        """導覽列／頁尾不得混入 content——會毒化 RAG 檢索（F4 富邦教訓）。"""
        url = "https://www.icashpay.com.tw/advertMessage/view/id/2407"
        offer = icashpay.parse_detail(read_fixture("icashpay_detail.html"), url, SCRAPED_AT)
        assert "APP下載" not in offer.content
        assert "常見問題" not in offer.content
        assert "愛金卡股份有限公司 All Rights Reserve" not in offer.content

    def test_parse_detail_raises_on_blank_page(self):
        with pytest.raises(ValueError):
            icashpay.parse_detail("<html></html>", "https://example.com/x", SCRAPED_AT)


class TestIcashpayFetch:
    def test_fetch_walks_index_pages_then_details(self):
        list_html = read_fixture("icashpay_list.html")
        detail_html = read_fixture("icashpay_detail.html")

        def fake_get(url: str) -> str:
            if url == icashpay.INDEX_URL or "/advertMessage/index/page/" in url:
                return list_html
            assert "/advertMessage/view/id/" in url
            return detail_html

        offers = icashpay.fetch(fake_get)
        # 6 個分頁回同一份列表，明細去重後 = 列表內不重複連結數
        assert len(offers) == 6
        assert all(o.provider == "icash Pay" for o in offers)

    def test_fetch_uses_index_as_first_page_without_refetching(self):
        """首頁抓完就當第 1 頁用：不重抓 page/1（省請求），且就算分頁把
        「目前頁」改成非連結、page/1 從清單消失，第 1 頁的優惠也不會漏。"""
        list_html = read_fixture("icashpay_list.html")
        detail_html = read_fixture("icashpay_detail.html")
        calls: list[str] = []

        def counting_get(url: str) -> str:
            calls.append(url)
            if url == icashpay.INDEX_URL or "/advertMessage/index/page/" in url:
                return list_html
            return detail_html

        icashpay.fetch(counting_get)
        assert not any(u.endswith("/page/1") for u in calls)  # 首頁內容不抓第二次
        assert calls.count(icashpay.INDEX_URL) == 1

    def test_fetch_skips_detail_on_http_error(self):
        import requests

        list_html = read_fixture("icashpay_list.html")
        detail_html = read_fixture("icashpay_detail.html")
        broken_url = icashpay.list_detail_urls(list_html)[0]

        def flaky_get(url: str) -> str:
            if url == icashpay.INDEX_URL or "/advertMessage/index/page/" in url:
                return list_html
            if url == broken_url:
                raise requests.HTTPError("503")
            return detail_html

        assert len(icashpay.fetch(flaky_get)) == 5
