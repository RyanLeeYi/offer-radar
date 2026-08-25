"""F22：iPASS 一卡通 News 資料源測試。全程 fixture HTML + fake LLM，不打真站。

驗收對應：
- 列表頁解析：文章連結（去重）、分頁（N 頁）串接與超出頁數提早停止
- 文章內文抽取（scraper 側）：標題 + 內文、去除分享按鈕與 script；缺 article-post 視為
  版面已改/文章已下架，raise ValueError
- LLM 結構化抽取（rag 側）：成功入庫欄位正確（trust_tier=verified，非 web_unverified，
  與既有五個官方一手來源同級）、非優惠新聞跳過不中斷整批
- 組裝入口 rag/ipass_ingest.py：端到端串接、回報抓到/入庫筆數、單篇失敗不中斷整批
"""

from datetime import datetime
from pathlib import Path

import pytest

from rag.ipass_extractor import Article, extract_offers
from rag.ipass_ingest import ingest_ipassmoney
from scraper.db import init_db, list_offers
from scraper.sources import ipassmoney

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 25, 10, 0, 0)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestListArticleUrls:
    def test_extracts_article_links_deduped(self):
        urls = ipassmoney.list_article_urls(read_fixture("ipassmoney_list_p1.html"))
        assert urls == [
            "https://www.i-pass.com.tw/News/Detail/104299",
            "https://www.i-pass.com.tw/News/Detail/104302",
        ]

    def test_no_listpost_divs_returns_empty(self):
        assert ipassmoney.list_article_urls("<html><body>沒有文章</body></html>") == []


class TestFetchRecentArticleUrls:
    def test_default_pages_one_only_hits_page_one(self):
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return read_fixture("ipassmoney_list_p1.html")

        urls = ipassmoney.fetch_recent_article_urls(get)
        assert calls == [ipassmoney.NEWS_URL]
        assert len(urls) == 2

    def test_pages_two_fetches_query_page(self):
        pages = {
            ipassmoney.NEWS_URL: read_fixture("ipassmoney_list_p1.html"),
            f"{ipassmoney.NEWS_URL}?page=2": read_fixture("ipassmoney_list_p2.html"),
        }
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return pages[url]

        urls = ipassmoney.fetch_recent_article_urls(get, pages=2)
        assert calls == [ipassmoney.NEWS_URL, f"{ipassmoney.NEWS_URL}?page=2"]
        assert urls[-1] == "https://www.i-pass.com.tw/News/Detail/104261"

    def test_pages_beyond_available_stops_early(self):
        """要求 5 頁但第 2 頁已無文章：不報錯，抓到多少算多少。"""
        pages = {
            ipassmoney.NEWS_URL: read_fixture("ipassmoney_list_p1.html"),
            f"{ipassmoney.NEWS_URL}?page=2": read_fixture("ipassmoney_list_empty.html"),
        }
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return pages[url]

        ipassmoney.fetch_recent_article_urls(get, pages=5)
        assert calls == [ipassmoney.NEWS_URL, f"{ipassmoney.NEWS_URL}?page=2"]

    def test_pages_less_than_one_treated_as_one(self):
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return read_fixture("ipassmoney_list_p1.html")

        ipassmoney.fetch_recent_article_urls(get, pages=0)
        assert calls == [ipassmoney.NEWS_URL]


class TestParseArticle:
    def test_extracts_title_and_body_excludes_share_buttons(self):
        text = ipassmoney.parse_article(
            read_fixture("ipassmoney_article_offer.html"), "https://example/article"
        )
        assert "8 月必收優惠" in text
        assert "回饋率高達 33%" in text
        assert "repost-line" not in text  # 分享按鈕圖片 alt 已剔除（連同 post-repo 整塊）
        assert "fbs_click" not in text  # script 已剔除

    def test_missing_article_raises_value_error(self):
        with pytest.raises(ValueError, match="article-post"):
            ipassmoney.parse_article(
                read_fixture("ipassmoney_article_missing.html"), "https://example/missing"
            )


OFFER_PAYLOAD = {
    "source_type": "e_payment",
    "bank": None,
    "provider": "一卡通 iPASS MONEY",
    "title": "8 月必收優惠：7-ELEVEN 滿 159 送 50 元券",
    "content": "7-ELEVEN 使用 iPASS MONEY APP 綁定信用卡付款，單筆消費滿 159 元可兌換 50 元優惠券",
    "channel": "7-ELEVEN",
    "reward_rate": "33%",
}


class TestExtractOffers:
    def test_valid_extraction_sets_verified(self):
        import json

        article = Article(url="https://i-pass.com.tw/a", text="8 月優惠活動內容")
        offers = extract_offers(
            [article], lambda p: json.dumps(OFFER_PAYLOAD, ensure_ascii=False), NOW
        )
        assert len(offers) == 1
        offer = offers[0]
        assert offer.trust_tier == "verified"  # 與既有五個官方來源同級，非 web_unverified
        assert offer.expires_at is None
        assert offer.source_url == "https://i-pass.com.tw/a"
        assert offer.provider == "一卡通 iPASS MONEY"
        assert offer.reward_rate == "33%"  # reward_rate 保留原文不解析

    def test_non_offer_news_dropped_not_raised(self):
        article = Article(url="https://i-pass.com.tw/b", text="董事長交接人事公告")
        offers = extract_offers([article], lambda p: '{"source_type": null}', NOW)
        assert offers == []

    def test_one_bad_article_does_not_block_others(self):
        good = Article(url="https://i-pass.com.tw/good", text="好文章")
        bad = Article(url="https://i-pass.com.tw/bad", text="壞文章")

        def fake_complete(prompt: str) -> str:
            if "bad" in prompt:
                return "這篇看不出有優惠活動"  # 非 JSON，抽不出來
            import json

            return json.dumps(OFFER_PAYLOAD, ensure_ascii=False)

        offers = extract_offers([bad, good], fake_complete, NOW)
        assert len(offers) == 1
        assert offers[0].source_url == "https://i-pass.com.tw/good"


class TestIngestIpassmoney:
    def test_end_to_end_fetch_extract_store(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        pages = {ipassmoney.NEWS_URL: read_fixture("ipassmoney_list_p1.html")}
        articles_by_url = {
            "https://www.i-pass.com.tw/News/Detail/104299": read_fixture(
                "ipassmoney_article_offer.html"
            ),
            "https://www.i-pass.com.tw/News/Detail/104302": read_fixture(
                "ipassmoney_article_no_offer.html"
            ),
        }

        def get(url: str) -> str:
            return pages.get(url) or articles_by_url[url]

        import json

        def complete(prompt: str) -> str:
            if "7-ELEVEN" in prompt or "必收優惠" in prompt:
                return json.dumps(OFFER_PAYLOAD, ensure_ascii=False)
            return '{"source_type": null}'

        result = ingest_ipassmoney(conn, get, complete, NOW)

        assert (result.fetched, result.stored) == (2, 1)
        [offer] = list_offers(conn)
        assert offer.trust_tier == "verified"
        assert offer.provider == "一卡通 iPASS MONEY"

    def test_article_fetch_failure_does_not_abort_run(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        pages = {ipassmoney.NEWS_URL: read_fixture("ipassmoney_list_p1.html")}
        articles_by_url = {
            "https://www.i-pass.com.tw/News/Detail/104299": read_fixture(
                "ipassmoney_article_missing.html"
            ),
            "https://www.i-pass.com.tw/News/Detail/104302": read_fixture(
                "ipassmoney_article_offer.html"
            ),
        }

        def get(url: str) -> str:
            return pages.get(url) or articles_by_url[url]

        import json

        def complete(prompt: str) -> str:
            return json.dumps(OFFER_PAYLOAD, ensure_ascii=False)

        result = ingest_ipassmoney(conn, get, complete, NOW)

        # 第一篇（版面缺 article-post）抓取失敗跳過，第二篇正常處理 → fetched=1
        assert result.fetched == 1
        assert result.stored == 1
