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
        self._collection()  # 確保 collection 存在

    def _collection(self):
        """每次重新解析 collection，不快取 handle。

        Chroma 的 Collection 物件把 UUID 與 metadata 定死在取得當下——長駐 API
        期間若另一個 process 跑 ingest（rebuild 換新 collection），快取的 handle
        會炸 NotFoundError、metadata 永遠是舊值。get_or_create 是本地 sqlite
        查詢，成本可忽略。
        """
        return self._client.get_or_create_collection(self._name, metadata=_SPACE)

    def upsert(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if not ids:
            return
        self._collection().upsert(
            ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas
        )

    def count(self) -> int:
        return self._collection().count()

    def distinct_offer_count(self) -> int:
        """R3 驗收口徑：進了庫的「優惠」數（一優惠可能多 chunk）。"""
        return len({m["offer_id"] for m in self.all_metadatas()})

    def all_metadatas(self) -> list[dict]:
        if self._collection().count() == 0:
            return []
        return self._collection().get(include=["metadatas"])["metadatas"]

    def query(self, embedding: list[float], top_k: int) -> list[Hit]:
        """以向量查 top_k 近鄰，依 distance 升冪回傳。"""
        available = self._collection().count()
        if available == 0:
            return []
        result = self._collection().query(
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
        available = self._collection().count()
        if available == 0:
            return []
        result = self._collection().query(
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

    def set_ingest_stats(self, when: str, offers: int) -> None:
        """記錄最近一次 ingest 的時間（ISO 字串）與優惠數，存 collection metadata。

        offers 數快取在這裡讓 /health 高頻讀取不用全量掃 metadata。
        """
        collection = self._collection()
        # modify 不准帶 hnsw:* 鍵（距離函數建庫後不可改），merge 時剔除
        merged = {
            key: value
            for key, value in (collection.metadata or {}).items()
            if not key.startswith("hnsw:")
        }
        merged["last_ingest_at"] = when
        merged["offers_count"] = offers
        collection.modify(metadata=merged)

    def last_ingest_at(self) -> str | None:
        return (self._collection().metadata or {}).get("last_ingest_at")

    def offers_count(self) -> int:
        """進了庫的優惠數：優先讀 ingest 寫入的快取，舊庫（沒寫過 stats）退回全量掃。"""
        cached = (self._collection().metadata or {}).get("offers_count")
        return cached if isinstance(cached, int) else self.distinct_offer_count()

    def rebuild(self) -> None:
        """清空重建 collection：全量 ingest 的第一步。

        注意：collection metadata（含 ingest stats）一併清空，
        ingest 流程要在重建後重新 set_ingest_stats。
        """
        self._client.delete_collection(self._name)
        self._collection()
