"""ChromaDB 唯一入口（ARCHITECTURE 邊界：其他模組一律經這裡，不直接 import chromadb）。

collection 常駐一份（offers）；ingest 走全量重建（rebuild → upsert），
過期優惠隨重建自然消失，重跑天然 idempotent。
"""

import chromadb

COLLECTION_NAME = "offers"


class VectorStore:
    def __init__(self, path: str, collection_name: str = COLLECTION_NAME) -> None:
        self._client = chromadb.PersistentClient(path=path)
        self._name = collection_name
        self._collection = self._client.get_or_create_collection(collection_name)

    def upsert(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if not ids:
            return
        self._collection.upsert(
            ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas
        )

    def count(self) -> int:
        return self._collection.count()

    def distinct_offer_count(self) -> int:
        """R3 驗收口徑：進了庫的「優惠」數（一優惠可能多 chunk）。"""
        return len({m["offer_id"] for m in self.all_metadatas()})

    def all_metadatas(self) -> list[dict]:
        if self._collection.count() == 0:
            return []
        return self._collection.get(include=["metadatas"])["metadatas"]

    def rebuild(self) -> None:
        """清空重建 collection：全量 ingest 的第一步。"""
        self._client.delete_collection(self._name)
        self._collection = self._client.get_or_create_collection(self._name)
