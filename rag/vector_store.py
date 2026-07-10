"""ChromaDB 唯一入口（ARCHITECTURE 邊界：其他模組一律經這裡，不直接 import chromadb）。

collection 常駐一份（offers）；ingest 走全量重建（rebuild → upsert），
過期優惠隨重建自然消失，重跑天然 idempotent。
"""

from dataclasses import dataclass

import chromadb

COLLECTION_NAME = "offers"
# cosine：檢索相似度與向量長度無關（L2 會被文長影響）。只在建 collection 時生效，
# 既有 L2 collection 要跑一次 rebuild（ingest 本來就是全量重建）才會切換。
_SPACE = {"hnsw:space": "cosine"}


@dataclass(frozen=True)
class Hit:
    """一筆檢索結果：distance 越小越相關（cosine distance ∈ [0, 2]）。

    keyword_match=True 表示由關鍵詞精確匹配（$contains）取得——高信心，
    pipeline 的向量距離門檻對其不適用。
    """

    text: str
    metadata: dict
    distance: float
    keyword_match: bool = False


class VectorStore:
    def __init__(self, path: str, collection_name: str = COLLECTION_NAME) -> None:
        self._client = chromadb.PersistentClient(path=path)
        self._name = collection_name
        self._collection = self._client.get_or_create_collection(
            collection_name, metadata=_SPACE
        )

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

    def query(self, embedding: list[float], top_k: int) -> list[Hit]:
        """以向量查 top_k 近鄰，依 distance 升冪回傳。"""
        available = self._collection.count()
        if available == 0:
            return []
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, available),
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(text=text, metadata=metadata, distance=distance)
            for text, metadata, distance in zip(
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]

    def query_containing(self, term: str, embedding: list[float], top_k: int) -> list[Hit]:
        """只在「內文含 term」的文件裡做向量排序——混合檢索的關鍵詞腿。"""
        available = self._collection.count()
        if available == 0:
            return []
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, available),
            where_document={"$contains": term},
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(text=text, metadata=metadata, distance=distance)
            for text, metadata, distance in zip(
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]

    def rebuild(self) -> None:
        """清空重建 collection：全量 ingest 的第一步。"""
        self._client.delete_collection(self._name)
        self._collection = self._client.get_or_create_collection(self._name, metadata=_SPACE)
