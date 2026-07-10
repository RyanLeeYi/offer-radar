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


def test_rebuild_clears_previous_content(tmp_path):
    store = make_store(tmp_path)
    upsert_two(store)
    store.rebuild()
    assert store.count() == 0
    # rebuild 後可直接再寫（過期優惠隨重建消失，R3/R4 的過濾基礎）
    upsert_two(store)
    assert store.count() == 2
