"""rag.ingest 端到端測試（PRD R3）：tmp SQLite + tmp ChromaDB + 注入假 embedder。

驗收對應：
- distinct offer_id 數 = SQLite 未過期優惠筆數（valid_to null 或 ≥ 今天）
- 每 chunk metadata 含 offer_id / valid_to / source_url
- 重跑 idempotent（全量重建）
"""

from datetime import date, datetime, timedelta

from rag.ingest import ingest
from rag.vector_store import VectorStore
from scraper.db import init_db, upsert_offer
from scraper.models import Offer

TODAY = date(2026, 7, 10)
SCRAPED_AT = datetime(2026, 7, 10, 12, 0, 0)


def fake_embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 1.0] for t in texts]


def make_offer(title: str, content: str, valid_to: date | None) -> Offer:
    return Offer(
        source_type="credit_card",
        bank="測試銀行",
        provider=None,
        title=title,
        content=content,
        channel=None,
        reward_rate=None,
        valid_from=None,
        valid_to=valid_to,
        source_url=f"https://example.com/{title}",
        scraped_at=SCRAPED_AT,
    )


def seed_offers(conn) -> None:
    upsert_offer(conn, make_offer("有效優惠", "內容甲", date(2026, 12, 31)))
    upsert_offer(conn, make_offer("無期限優惠", "內容乙", None))
    upsert_offer(conn, make_offer("過期優惠", "內容丙", date(2026, 1, 1)))
    upsert_offer(conn, make_offer("長文優惠", "丁" * 1200, date(2026, 12, 31)))
    conn.commit()


def test_ingest_matches_active_offers_and_metadata(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    seed_offers(conn)
    store = VectorStore(path=str(tmp_path / "chroma"))

    result = ingest(conn, store, fake_embed, today=TODAY)

    assert result.offers == 3  # 過期的那筆不進庫
    assert store.distinct_offer_count() == 3
    assert result.chunks >= 4  # 長文優惠切成多塊
    assert store.count() == result.chunks

    for metadata in store.all_metadatas():
        assert set(metadata) >= {"offer_id", "valid_to", "source_url"}
        assert metadata["source_url"].startswith("https://example.com/")


def test_ingest_excludes_expired_title(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    seed_offers(conn)
    store = VectorStore(path=str(tmp_path / "chroma"))
    ingest(conn, store, fake_embed, today=TODAY)

    urls = {m["source_url"] for m in store.all_metadatas()}
    assert "https://example.com/過期優惠" not in urls


def test_ingest_rerun_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    seed_offers(conn)
    store = VectorStore(path=str(tmp_path / "chroma"))

    first = ingest(conn, store, fake_embed, today=TODAY)
    second = ingest(conn, store, fake_embed, today=TODAY)

    assert (first.offers, first.chunks) == (second.offers, second.chunks)
    assert store.count() == first.chunks


def test_list_active_offers_filters_and_returns_ids(tmp_path):
    from scraper.db import list_active_offers

    conn = init_db(tmp_path / "offers.db")
    seed_offers(conn)
    rows = list_active_offers(conn, today=TODAY)
    titles = [offer.title for _, offer in rows]
    assert "過期優惠" not in titles
    assert len(rows) == 3
    ids = [offer_id for offer_id, _ in rows]
    assert len(set(ids)) == 3 and all(isinstance(i, int) for i in ids)


def test_ingest_records_ingest_stats(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    seed_offers(conn)
    store = VectorStore(path=str(tmp_path / "chroma"))
    assert store.last_ingest_at() is None

    ingest(conn, store, fake_embed, today=TODAY)

    recorded = store.last_ingest_at()
    assert recorded is not None
    datetime.fromisoformat(recorded)  # ISO 格式可解析（/health 直接透傳）
    assert store.offers_count() == 3  # 未過期優惠數一併存 metadata


def test_ingest_empty_db_yields_empty_store(tmp_path):
    conn = init_db(tmp_path / "offers.db")
    store = VectorStore(path=str(tmp_path / "chroma"))
    result = ingest(conn, store, fake_embed, today=TODAY)
    assert (result.offers, result.chunks) == (0, 0)
    assert store.count() == 0


def make_web_offer(title: str, expires_at: datetime | None) -> Offer:
    """網搜來源的假資料：trust_tier=web_unverified，帶 TTL。"""
    return Offer(
        source_type="credit_card",
        bank="網搜銀行",
        provider=None,
        title=title,
        content="網搜抽出來的內容",
        channel=None,
        reward_rate=None,
        valid_from=None,
        valid_to=None,
        source_url=f"https://example.com/web/{title}",
        scraped_at=SCRAPED_AT,
        trust_tier="web_unverified",
        expires_at=expires_at,
    )


class TestTrustTier:
    """F12：chunk metadata 帶 trust_tier，過期的 web_unverified 不進 ChromaDB。"""

    def test_chunk_metadata_carries_trust_tier(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        seed_offers(conn)
        upsert_offer(conn, make_web_offer("網搜優惠", datetime(2099, 1, 1)))
        conn.commit()
        store = VectorStore(path=str(tmp_path / "chroma"))

        ingest(conn, store, fake_embed, today=TODAY)

        tiers = {m["title"]: m["trust_tier"] for m in store.all_metadatas()}
        assert tiers["有效優惠"] == "verified"
        assert tiers["網搜優惠"] == "web_unverified"

    def test_expired_web_unverified_excluded(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        upsert_offer(conn, make_web_offer("過期網搜", datetime(2020, 1, 1)))
        upsert_offer(conn, make_web_offer("未過期網搜", datetime(2099, 1, 1)))
        conn.commit()
        store = VectorStore(path=str(tmp_path / "chroma"))

        result = ingest(conn, store, fake_embed, today=TODAY)

        titles = {m["title"] for m in store.all_metadatas()}
        assert titles == {"未過期網搜"}
        assert result.offers == 1

    def test_verified_offers_never_expire(self, tmp_path):
        """既有爬蟲資料沒有 expires_at → TTL 過濾對它們完全無作用（行為不變）。"""
        conn = init_db(tmp_path / "offers.db")
        seed_offers(conn)
        store = VectorStore(path=str(tmp_path / "chroma"))
        assert ingest(conn, store, fake_embed, today=TODAY).offers == 3


class TestExpiryBoundary:
    def test_list_active_offers_uses_injected_now(self, tmp_path):
        from scraper.db import list_active_offers

        conn = init_db(tmp_path / "offers.db")
        expires = datetime(2026, 7, 10, 12, 0, 0)
        upsert_offer(conn, make_web_offer("剛好到期", expires))
        conn.commit()

        just_before = list_active_offers(conn, today=TODAY, now=expires - timedelta(seconds=1))
        assert len(just_before) == 1
        at_expiry = list_active_offers(conn, today=TODAY, now=expires)
        assert at_expiry == []

    def test_valid_to_and_expires_at_filter_independently(self, tmp_path):
        from scraper.db import list_active_offers

        conn = init_db(tmp_path / "offers.db")
        upsert_offer(conn, make_offer("過期日期", "內容", date(2026, 1, 1)))  # valid_to 已過
        upsert_offer(conn, make_web_offer("未過期網搜", datetime(2099, 1, 1)))
        conn.commit()

        rows = list_active_offers(conn, today=TODAY, now=datetime(2026, 7, 10, 12, 0, 0))
        assert [o.title for _, o in rows] == ["未過期網搜"]
