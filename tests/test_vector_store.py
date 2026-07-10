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


def test_rebuild_clears_previous_content(tmp_path):
    store = make_store(tmp_path)
    upsert_two(store)
    store.rebuild()
    assert store.count() == 0
    # rebuild 後可直接再寫（過期優惠隨重建消失，R3/R4 的過濾基礎）
    upsert_two(store)
    assert store.count() == 2
