"""F23：失敗頁自癒抽取測試。全程 fixture/inline HTML + fake LLM，不打真站。

驗收對應：
- 腿一存證（scraper 側）：解析擲例外觸發存證、頁面抓取成功但解析出 0 筆觸發存證，
  且不中斷該輪其他來源；HTTP 抓取失敗（非解析失敗）不存證，行為與既有測試一致
- rag/selfheal.py：HTML 去雜訊轉純文字（bs4）、LLM 抽取成功入庫並帶 llm_fallback
  標記、抽取失敗跳過不中斷整批
- rag/pipeline.py：查詢回答引用到 llm_fallback 資料時附警語，且不連坐標示其他 tier
- scraper/db.py：verified 資料不被 llm_fallback 覆蓋（既有 web_unverified 保護的推廣）
"""

import json
import logging
from datetime import datetime, timedelta

import requests

from rag.pipeline import FALLBACK_WARNING, UNVERIFIED_WARNING, Pipeline
from rag.selfheal import extract_offers, html_to_text, selfheal
from rag.vector_store import Hit
from scraper.db import init_db, list_offers, upsert_offer
from scraper.models import Offer
from scraper.sources import cathay
from scraper.sources._shared import (
    FailedPage,
    archive_failed_page,
    fetch_listed_details,
    read_failed_pages,
)

NOW = datetime(2026, 8, 25, 10, 0, 0)


def make_offer(**overrides) -> Offer:
    fields = {
        "source_type": "credit_card",
        "bank": "台新",
        "provider": None,
        "title": "測試優惠",
        "content": "測試內容",
        "channel": None,
        "reward_rate": None,
        "valid_from": None,
        "valid_to": None,
        "source_url": "https://example.com/offer",
        "scraped_at": NOW,
    }
    fields.update(overrides)
    return Offer(**fields)


class TestArchiveFailedPage:
    def test_round_trips_source_url_reason_and_html(self, tmp_path):
        path = archive_failed_page(
            "taishin", "https://example.com/a?x=1&y=2", "<html>內容</html>", "parse_error", NOW, tmp_path
        )
        assert path is not None and path.exists()

        [page] = read_failed_pages(tmp_path)
        assert page.source == "taishin"
        assert page.url == "https://example.com/a?x=1&y=2"
        assert page.reason == "parse_error"
        assert page.html == "<html>內容</html>"
        assert page.archived_at == NOW

    def test_missing_dir_returns_empty(self, tmp_path):
        assert read_failed_pages(tmp_path / "does-not-exist") == []

    def test_unrelated_html_file_ignored(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "not-a-failed-page.html").write_text("<html></html>", encoding="utf-8")
        assert read_failed_pages(tmp_path) == []

    def test_write_failure_logged_not_raised(self, tmp_path):
        """磁碟寫入失敗（如目錄其實是檔案）只記警告，不中斷呼叫端。"""
        blocked = tmp_path / "blocked"
        blocked.write_text("我是檔案不是目錄", encoding="utf-8")
        assert archive_failed_page("taishin", "https://x", "<html></html>", "parse_error", NOW, blocked) is None


class TestFetchListedDetailsArchiving:
    """直接測 scraper/sources/_shared.py 的通用管線，不依賴任何特定來源檔。"""

    def _logger(self, name="faketest"):
        return logging.getLogger(f"scraper.sources.{name}")

    def test_parse_error_archives_page_and_skips_other_sources_unaffected(self, tmp_path):
        def parse_detail(html, url, now):
            if "broken" in url:
                raise ValueError("版面已改")
            return make_offer(source_url=url)

        def get(url):
            return f"<html>{url}</html>"

        offers = fetch_listed_details(
            get,
            ["https://cat"],
            lambda html: ["https://x/broken", "https://x/ok"],
            parse_detail,
            self._logger(),
            tmp_path,
        )

        assert len(offers) == 1  # 壞的那頁被丟棄，好的那頁照常入列，不中斷整批
        assert offers[0].source_url == "https://x/ok"

        [page] = read_failed_pages(tmp_path)
        assert page.reason == "parse_error"
        assert page.source == "faketest"
        assert page.url == "https://x/broken"
        assert page.html == "<html>https://x/broken</html>"

    def test_zero_detail_links_archives_listing_page(self, tmp_path):
        offers = fetch_listed_details(
            lambda url: f"<html>listing:{url}</html>",
            ["https://cat/a", "https://cat/b"],
            lambda html: [] if "cat/a" in html else ["https://x/ok"],
            lambda html, url, now: make_offer(source_url=url),
            self._logger(),
            tmp_path,
        )

        assert len(offers) == 1  # 另一個列表頁正常，不中斷整批

        [page] = read_failed_pages(tmp_path)
        assert page.reason == "zero_results"
        assert page.url == "https://cat/a"

    def test_http_error_fetching_detail_is_not_archived(self, tmp_path):
        """既有行為不變：抓取（非解析）失敗只記 log 跳過，沒有 HTML 可存、不存證。"""

        def get(url):
            if "broken" in url:
                raise requests.HTTPError("503")
            return "<html>ok</html>"

        offers = fetch_listed_details(
            get,
            ["https://cat"],
            lambda html: ["https://x/broken", "https://x/ok"],
            lambda html, url, now: make_offer(source_url=url),
            self._logger(),
            tmp_path,
        )

        assert len(offers) == 1
        assert read_failed_pages(tmp_path) == []  # 沒有存證檔


class TestCathayFetchArchiving:
    """cathay.py 走自己的抓取迴圈（sitemap，非 fetch_listed_details），F23 存證
    比照同一套規則各自呼叫 archive_failed_page，這裡直接測 cathay.fetch 本身。"""

    _EVENT_JSON = json.dumps({"title": "測試活動", ":items": {"cub_texta": {"text": "內容"}}})

    def _sitemap(self, *urls: str) -> str:
        locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        return f"<urlset>{locs}</urlset>"

    def test_parse_error_archives_page_and_other_events_unaffected(self, tmp_path):
        good_url = "https://www.cathay-cube.com.tw/event/overview/credit-card/shopping/202607/good"
        broken_url = "https://www.cathay-cube.com.tw/event/overview/credit-card/shopping/202607/broken"
        sitemap = self._sitemap(good_url, broken_url)

        def get(url):
            if url == cathay.SITEMAP_URL:
                return sitemap
            if url == broken_url + ".model.json":
                return "{}"  # 缺 title，parse_event 會 raise ValueError
            return self._EVENT_JSON

        offers = cathay.fetch(get, tmp_path)

        assert len(offers) == 1  # 壞的那頁被丟棄，好的那頁照常入列，不中斷整批
        assert offers[0].source_url == good_url

        [page] = read_failed_pages(tmp_path)
        assert page.reason == "parse_error"
        assert page.source == "cathay"
        assert page.url == broken_url
        assert page.html == "{}"
        assert datetime.now() - page.archived_at < timedelta(minutes=1)

    def test_zero_event_urls_archives_sitemap(self, tmp_path):
        sitemap = self._sitemap("https://www.cathay-cube.com.tw/other/not-an-event")

        offers = cathay.fetch(lambda url: sitemap, tmp_path)

        assert offers == []
        [page] = read_failed_pages(tmp_path)
        assert page.reason == "zero_results"
        assert page.source == "cathay"
        assert page.url == cathay.SITEMAP_URL
        assert page.html == sitemap
        assert datetime.now() - page.archived_at < timedelta(minutes=1)

    def test_http_error_fetching_event_page_is_not_archived(self, tmp_path):
        """既有行為不變：抓取（非解析）失敗只記 log 跳過，沒有內容可存、不存證。"""
        good_url = "https://www.cathay-cube.com.tw/event/overview/credit-card/shopping/202607/good"
        broken_url = "https://www.cathay-cube.com.tw/event/overview/credit-card/shopping/202607/broken"
        sitemap = self._sitemap(good_url, broken_url)

        def get(url):
            if url == cathay.SITEMAP_URL:
                return sitemap
            if url == broken_url + ".model.json":
                raise requests.ConnectionError("connection reset")
            return self._EVENT_JSON

        offers = cathay.fetch(get, tmp_path)

        assert len(offers) == 1
        assert read_failed_pages(tmp_path) == []  # 沒有存證檔

    def test_normal_path_all_events_parsed_and_nothing_archived(self, tmp_path):
        good_url = "https://www.cathay-cube.com.tw/event/overview/credit-card/shopping/202607/good"
        sitemap = self._sitemap(good_url)

        def get(url):
            return sitemap if url == cathay.SITEMAP_URL else self._EVENT_JSON

        offers = cathay.fetch(get, tmp_path)

        assert len(offers) == 1
        assert offers[0].source_url == good_url
        assert read_failed_pages(tmp_path) == []


class TestExtractOffers:
    OFFER_PAYLOAD = {
        "source_type": "credit_card",
        "bank": "台新",
        "provider": None,
        "title": "自癒抽取的優惠",
        "content": "活動內容",
        "channel": None,
        "reward_rate": "5%",
    }

    def _page(self, url="https://example.com/broken", html="<html><body>優惠內容</body></html>"):
        return FailedPage(
            source="taishin", url=url, reason="parse_error", archived_at=NOW, html=html, path=None
        )

    def test_valid_extraction_stores_llm_fallback_without_ttl(self):
        offers = extract_offers(
            [self._page()], lambda p: json.dumps(self.OFFER_PAYLOAD, ensure_ascii=False), NOW
        )
        assert len(offers) == 1
        offer = offers[0]
        assert offer.trust_tier == "llm_fallback"
        assert offer.expires_at is None
        assert offer.source_url == "https://example.com/broken"
        assert offer.title == "自癒抽取的優惠"
        assert offer.reward_rate == "5%"  # reward_rate 保留原文不解析

    def test_no_offer_found_dropped_not_raised(self):
        offers = extract_offers([self._page()], lambda p: '{"source_type": null}', NOW)
        assert offers == []

    def test_non_json_reply_dropped_not_raised(self):
        offers = extract_offers([self._page()], lambda p: "看不出有優惠活動", NOW)
        assert offers == []

    def test_one_bad_page_does_not_block_others(self):
        good = self._page(url="https://x/good")
        bad = self._page(url="https://x/bad")

        def fake_complete(prompt: str) -> str:
            if "bad" in prompt:
                return "無法判讀"
            return json.dumps(self.OFFER_PAYLOAD, ensure_ascii=False)

        offers = extract_offers([bad, good], fake_complete, NOW)
        assert len(offers) == 1
        assert offers[0].source_url == "https://x/good"


class TestHtmlToText:
    def test_strips_script_and_style_keeps_body_text(self):
        html = "<html><head><style>.a{}</style></head><body><script>x()</script>優惠內容</body></html>"
        text = html_to_text(html)
        assert "優惠內容" in text
        assert "x()" not in text and ".a{}" not in text


class TestSelfheal:
    def test_end_to_end_extract_and_store(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        pages = [
            FailedPage(
                source="taishin",
                url="https://example.com/broken",
                reason="parse_error",
                archived_at=NOW,
                html="<html><body>優惠內容</body></html>",
                path=None,
            )
        ]

        def complete(prompt: str) -> str:
            return json.dumps(TestExtractOffers.OFFER_PAYLOAD, ensure_ascii=False)

        stored = selfheal(conn, pages, complete, NOW)

        assert stored == 1
        [offer] = list_offers(conn)
        assert offer.trust_tier == "llm_fallback"
        assert offer.bank == "台新"


class TestFallbackWarning:
    """F23：查詢回答引用到 llm_fallback 資料時附警語（重用 F14 的判斷位置）。"""

    def _hit(self, offer_id: int, title: str, trust_tier: str) -> Hit:
        return Hit(
            text="內容",
            metadata={
                "offer_id": offer_id,
                "title": title,
                "valid_to": "2026-12-31",
                "source_url": f"https://example.com/{offer_id}",
                "trust_tier": trust_tier,
            },
            distance=0.10 + offer_id * 0.001,
        )

    def _build_pipeline(self, hits: list[Hit], reply: str = "推薦台新卡"):
        class FakeRetriever:
            def retrieve(self, question: str, top_k: int = 5) -> list[Hit]:
                return hits

        class FakeGenerator:
            def generate(self, question: str, hits: list[Hit]) -> str:
                return reply

        return Pipeline(retriever=FakeRetriever(), generator=FakeGenerator())

    def test_fallback_source_appends_fallback_warning(self):
        pipeline = self._build_pipeline([self._hit(1, "自癒抽取優惠", "llm_fallback")])
        result = pipeline.answer("問題")
        assert result.answer.startswith("推薦台新卡")
        assert FALLBACK_WARNING in result.answer
        assert "自癒抽取優惠" in result.answer.split(FALLBACK_WARNING)[1]

    def test_mixed_tiers_each_labeled_separately(self):
        pipeline = self._build_pipeline(
            [
                self._hit(1, "台新官網優惠", "verified"),
                self._hit(2, "網搜優惠", "web_unverified"),
                self._hit(3, "自癒抽取優惠", "llm_fallback"),
            ]
        )
        answer = pipeline.answer("問題").answer
        assert UNVERIFIED_WARNING in answer and FALLBACK_WARNING in answer
        unverified_block = answer.split(UNVERIFIED_WARNING)[1].split(FALLBACK_WARNING)[0]
        fallback_block = answer.split(FALLBACK_WARNING)[1]
        assert "網搜優惠" in unverified_block and "自癒抽取優惠" not in unverified_block
        assert "自癒抽取優惠" in fallback_block and "網搜優惠" not in fallback_block
        assert "台新官網優惠" not in unverified_block and "台新官網優惠" not in fallback_block

    def test_all_verified_answer_byte_identical(self):
        pipeline = self._build_pipeline([self._hit(1, "台新官網優惠", "verified")])
        assert pipeline.answer("問題").answer == "推薦台新卡"


class TestVerifiedNeverDowngradedByLlmFallback:
    """scraper/db.py 的保護推廣到 llm_fallback（既有測試只驗過 web_unverified）。"""

    def test_llm_fallback_does_not_overwrite_verified(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        verified = make_offer(content="官方版本")
        upsert_offer(conn, verified)
        upsert_offer(conn, make_offer(content="LLM 猜的版本", trust_tier="llm_fallback"))

        [got] = list_offers(conn)
        assert (got.trust_tier, got.content) == ("verified", "官方版本")

    def test_llm_fallback_trust_tier_accepted_by_model(self):
        offer = make_offer(trust_tier="llm_fallback")
        assert offer.trust_tier == "llm_fallback"
        assert offer.expires_at is None
