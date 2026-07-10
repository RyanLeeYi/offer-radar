"""VectorStore 測試：ChromaDB 唯一入口（ARCHITECTURE 邊界），用 tmp 路徑實測。"""

from rag.vector_store import VectorStore


def make_store(tmp_path) -> VectorStore:
    return VectorStore(path=str(tmp_path / "chroma"))


def upsert_two(store: VectorStore) -> None:
    store.upsert(
        ids=["1:0", "2:0"],
        texts=["優惠一", "優惠二"],
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
        metadatas=[
            {"offer_id": 1, "valid_to": "2026-12-31", "source_url": "https://a"},
            {"offer_id": 2, "valid_to": "", "source_url": "https://b"},
        ],
    )


def test_upsert_and_count(tmp_path):
    store = make_store(tmp_path)
    upsert_two(store)
    assert store.count() == 2


def test_upsert_same_ids_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    upsert_two(store)
    upsert_two(store)
    assert store.count() == 2


def test_distinct_offer_count(tmp_path):
    store = make_store(tmp_path)
    store.upsert(
        ids=["1:0", "1:1", "2:0"],
        texts=["長優惠上", "長優惠下", "短優惠"],
        embeddings=[[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]],
        metadatas=[
            {"offer_id": 1, "valid_to": "", "source_url": "https://a"},
            {"offer_id": 1, "valid_to": "", "source_url": "https://a"},
            {"offer_id": 2, "valid_to": "", "source_url": "https://b"},
        ],
    )
    assert store.count() == 3
    assert store.distinct_offer_count() == 2


def test_query_returns_nearest_first_with_metadata_and_distance(tmp_path):
    store = make_store(tmp_path)
    store.upsert(
        ids=["1:0", "2:0"],
        texts=["好市多刷卡回饋", "加油站優惠"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        metadatas=[
            {"offer_id": 1, "valid_to": "", "source_url": "https://a", "title": "好市多"},
            {"offer_id": 2, "valid_to": "", "source_url": "https://b", "title": "加油"},
        ],
    )
    hits = store.query(embedding=[0.9, 0.1], top_k=2)
    assert len(hits) == 2
    assert hits[0].text == "好市多刷卡回饋"
    assert hits[0].metadata["offer_id"] == 1
    assert hits[0].distance < hits[1].distance


def test_query_top_k_larger_than_collection(tmp_path):
    store = make_store(tmp_path)
    upsert_two(store)
    assert len(store.query(embedding=[0.1, 0.2], top_k=10)) == 2


def test_query_empty_collection_returns_empty(tmp_path):
    store = make_store(tmp_path)
    assert store.query(embedding=[0.1, 0.2], top_k=5) == []


def test_last_ingest_at_none_initially(tmp_path):
    store = make_store(tmp_path)
    assert store.last_ingest_at() is None


def test_ingest_stats_roundtrip_and_persists(tmp_path):
    store = make_store(tmp_path)
    store.set_ingest_stats(when="2026-07-10T22:00:00+08:00", offers=42)
    assert store.last_ingest_at() == "2026-07-10T22:00:00+08:00"
    # offers 數存 metadata，不用全量掃 chunk（/health 高頻呼叫）
    assert store.offers_count() == 42
    # 重新開啟同路徑（模擬 API 與 ingest 是不同 process）也讀得到
    reopened = make_store(tmp_path)
    assert reopened.last_ingest_at() == "2026-07-10T22:00:00+08:00"
    assert reopened.offers_count() == 42


def test_offers_count_falls_back_to_scan_without_stats(tmp_path):
    # 舊庫（ingest 還沒寫過 stats）退回掃 metadata，不用重建庫
    store = make_store(tmp_path)
    upsert_two(store)
    assert store.offers_count() == 2


def test_long_lived_store_survives_external_rebuild(tmp_path):
    """API 是長駐 process、ingest 是另一個 process：rebuild 換掉 collection 後，
    長駐端的既有 handle 不能炸 NotFoundError，且要看得到新的 ingest stats。"""
    api_store = make_store(tmp_path)
    upsert_two(api_store)
    assert api_store.count() == 2

    ingest_store = make_store(tmp_path)  # 模擬另一個 process
    ingest_store.rebuild()
    ingest_store.set_ingest_stats(when="2026-07-11T00:00:00+08:00", offers=0)

    assert api_store.count() == 0  # 不炸、看得到重建後的空庫
    assert api_store.last_ingest_at() == "2026-07-11T00:00:00+08:00"
    assert api_store.query(embedding=[0.1, 0.2], top_k=5) == []


def test_rebuild_clears_previous_content(tmp_path):
    store = make_store(tmp_path)
    upsert_two(store)
    store.rebuild()
    assert store.count() == 0
    # rebuild 後可直接再寫（過期優惠隨重建消失，R3/R4 的過濾基礎）
    upsert_two(store)
    assert store.count() == 2
