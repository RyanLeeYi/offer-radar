"""F21：PTT Lifeismoney 資料源測試。全程 fixture HTML + fake LLM，不打真站。

驗收對應：
- 列表頁解析：文章連結、已被刪除文章跳過、分頁（N 頁）串接與提早停止
- 文章內文抽取（scraper 側）：標題 + 內文、去除 metadata 與推文；缺 main-content 視為
  版面已改/文章已刪除，raise ValueError
- over18 cookie 帶入：build_session／build_client
- LLM 結構化抽取（rag 側）：成功入庫欄位正確（trust_tier=web_unverified）、
  驗證失敗跳過不中斷整批
- 組裝入口 rag/ptt_ingest.py：端到端串接、回報抓到/入庫筆數、單篇失敗不中斷整批
"""

from datetime import datetime
from pathlib import Path

import pytest

from rag.ptt_extractor import Article, extract_offers
from rag.ptt_ingest import ingest_lifeismoney
from scraper.db import init_db, list_offers
from scraper.sources import lifeismoney

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 25, 10, 0, 0)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestListArticleUrls:
    def test_extracts_article_links_skips_deleted(self):
        urls = lifeismoney.list_article_urls(read_fixture("lifeismoney_index.html"))
        assert urls == [
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000001.A.111.html",
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000002.A.222.html",
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000003.A.333.html",
        ]

    def test_no_title_divs_returns_empty(self):
        assert lifeismoney.list_article_urls("<html><body>沒有文章</body></html>") == []


class TestFetchRecentArticleUrls:
    def test_default_pages_one_only_hits_index(self):
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return read_fixture("lifeismoney_index.html")

        urls = lifeismoney.fetch_recent_article_urls(get)
        assert calls == [lifeismoney.INDEX_URL]
        assert len(urls) == 3

    def test_pages_two_walks_prev_page_link(self):
        pages = {
            lifeismoney.INDEX_URL: read_fixture("lifeismoney_index.html"),
            f"{lifeismoney.BASE_URL}/bbs/{lifeismoney.BOARD}/index3459.html": read_fixture(
                "lifeismoney_index_prev.html"
            ),
        }
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return pages[url]

        urls = lifeismoney.fetch_recent_article_urls(get, pages=2)
        assert calls == [
            lifeismoney.INDEX_URL,
            f"{lifeismoney.BASE_URL}/bbs/{lifeismoney.BOARD}/index3459.html",
        ]
        assert urls[-1] == "https://www.ptt.cc/bbs/Lifeismoney/M.1754900001.A.999.html"

    def test_pages_beyond_oldest_stops_early(self):
        """要求 5 頁但只有 2 頁資料（上頁連結 disabled）：不報錯，抓到多少算多少。"""
        pages = {
            lifeismoney.INDEX_URL: read_fixture("lifeismoney_index.html"),
            f"{lifeismoney.BASE_URL}/bbs/{lifeismoney.BOARD}/index3459.html": read_fixture(
                "lifeismoney_index_prev.html"
            ),
        }
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return pages[url]

        lifeismoney.fetch_recent_article_urls(get, pages=5)
        assert len(calls) == 2  # 第二頁的上頁連結已 disabled，不再往下走

    def test_pages_less_than_one_treated_as_one(self):
        calls: list[str] = []

        def get(url: str) -> str:
            calls.append(url)
            return read_fixture("lifeismoney_index.html")

        lifeismoney.fetch_recent_article_urls(get, pages=0)
        assert calls == [lifeismoney.INDEX_URL]


class TestParseArticle:
    def test_extracts_title_and_body_excludes_push(self):
        text = lifeismoney.parse_article(
            read_fixture("lifeismoney_article.html"), "https://example/article"
        )
        assert "國泰世華 CUBE卡 加碼 5% 回饋" in text
        assert "指定通路刷卡享 5% 回饋" in text
        assert "推推" not in text  # 推文已剔除
        assert "這張真香" not in text

    def test_deleted_article_raises_value_error(self):
        with pytest.raises(ValueError, match="main-content"):
            lifeismoney.parse_article(
                read_fixture("lifeismoney_article_deleted.html"), "https://example/deleted"
            )


class TestOver18Cookie:
    def test_build_session_carries_over18_cookie(self):
        session = lifeismoney.build_session()
        assert session.cookies.get("over18", domain=lifeismoney.OVER18_COOKIE_DOMAIN) == "1"

    def test_build_client_uses_over18_session(self):
        from scraper.http import PoliteClient

        client = lifeismoney.build_client()
        assert isinstance(client, PoliteClient)


OFFER_PAYLOAD = {
    "source_type": "credit_card",
    "bank": "國泰世華",
    "provider": None,
    "title": "CUBE卡 8月加碼 5% 回饋",
    "content": "指定通路刷卡享 5% 回饋，每人每月上限 300 元",
    "channel": None,
    "reward_rate": "5%",
}


class TestExtractOffers:
    def test_valid_extraction_sets_web_unverified(self):
        import json

        article = Article(url="https://ptt.cc/a", text="CUBE卡活動內容")
        offers = extract_offers(
            [article], lambda p: json.dumps(OFFER_PAYLOAD, ensure_ascii=False), NOW
        )
        assert len(offers) == 1
        offer = offers[0]
        assert offer.trust_tier == "web_unverified"
        assert offer.expires_at is None  # PTT 無查詢驅動的重跑機制，不設 TTL
        assert offer.source_url == "https://ptt.cc/a"
        assert offer.bank == "國泰世華"
        assert offer.reward_rate == "5%"  # reward_rate 保留原文不解析

    def test_validation_failure_dropped_not_raised(self):
        article = Article(url="https://ptt.cc/b", text="沒有優惠的閒聊文")
        offers = extract_offers([article], lambda p: '{"source_type": null}', NOW)
        assert offers == []

    def test_one_bad_article_does_not_block_others(self):
        good = Article(url="https://ptt.cc/good", text="好文章")
        bad = Article(url="https://ptt.cc/bad", text="壞文章")

        def fake_complete(prompt: str) -> str:
            if "bad" in prompt:
                return "這篇看不出有優惠活動"  # 非 JSON，抽不出來
            import json

            return json.dumps(OFFER_PAYLOAD, ensure_ascii=False)

        offers = extract_offers([bad, good], fake_complete, NOW)
        assert len(offers) == 1
        assert offers[0].source_url == "https://ptt.cc/good"


class TestIngestLifeismoney:
    def test_end_to_end_fetch_extract_store(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        pages = {lifeismoney.INDEX_URL: read_fixture("lifeismoney_index.html")}
        articles_by_url = {
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000001.A.111.html": read_fixture(
                "lifeismoney_article.html"
            ),
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000002.A.222.html": read_fixture(
                "lifeismoney_article_no_offer.html"
            ),
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000003.A.333.html": read_fixture(
                "lifeismoney_article_no_offer.html"
            ),
        }

        def get(url: str) -> str:
            return pages.get(url) or articles_by_url[url]

        import json

        def complete(prompt: str) -> str:
            if "國泰世華" in prompt:
                return json.dumps(OFFER_PAYLOAD, ensure_ascii=False)
            return '{"source_type": null}'

        result = ingest_lifeismoney(conn, get, complete, NOW)

        assert (result.fetched, result.stored) == (3, 1)
        [offer] = list_offers(conn)
        assert offer.trust_tier == "web_unverified"
        assert offer.bank == "國泰世華"

    def test_article_fetch_failure_does_not_abort_run(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        pages = {lifeismoney.INDEX_URL: read_fixture("lifeismoney_index.html")}
        articles_by_url = {
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000001.A.111.html": read_fixture(
                "lifeismoney_article_deleted.html"
            ),
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000002.A.222.html": read_fixture(
                "lifeismoney_article.html"
            ),
            "https://www.ptt.cc/bbs/Lifeismoney/M.1755000003.A.333.html": read_fixture(
                "lifeismoney_article_no_offer.html"
            ),
        }

        def get(url: str) -> str:
            return pages.get(url) or articles_by_url[url]

        import json

        def complete(prompt: str) -> str:
            return json.dumps(OFFER_PAYLOAD, ensure_ascii=False)

        result = ingest_lifeismoney(conn, get, complete, NOW)

        # 第一篇（已刪除）抓取失敗跳過，其餘兩篇正常處理 → fetched=2
        assert result.fetched == 2
        assert result.stored == 2  # 兩篇都能抽出（fake complete 一律回同一筆優惠）
