"""混合檢索：關鍵詞精確匹配（$contains）+ 向量語意檢索，合併去重。

為什麼要兩條腿（F4 實測）：商家名藏在長條款 chunk 裡會被向量稀釋
（「優食好市多專區」對好市多查詢掉出 top50），$contains 直達；
反過來，語意描述型問題（「便利商店有什麼行動支付優惠」）靠向量。
關鍵詞命中視為高信心，排在向量結果前面。
"""

from collections.abc import Callable
from dataclasses import replace

from rag.keywords import candidate_terms
from rag.vector_store import Hit, VectorStore

DEFAULT_TOP_K = 20  # 向量腿的量；生成端另有 context 上限（pipeline）
_KEYWORD_TOP_K = 3  # 每個關鍵詞 gram 取前幾筆
_KEYWORD_POOL = 8  # 關鍵詞腿總共貢獻的上限

QueryEmbedFn = Callable[[str], list[float]]


class Retriever:
    def __init__(self, store: VectorStore, embed_query: QueryEmbedFn) -> None:
        self._store = store
        self._embed_query = embed_query

    def retrieve(self, question: str, top_k: int = DEFAULT_TOP_K) -> list[Hit]:
        embedding = self._embed_query(question)
        keyword_hits = self._keyword_hits(question, embedding)
        vector_hits = self._store.query(embedding=embedding, top_k=top_k)
        return _merge(keyword_hits, vector_hits)

    def _keyword_hits(self, question: str, embedding: list[float]) -> list[Hit]:
        pool: list[Hit] = []
        for term in candidate_terms(question):
            pool.extend(
                replace(hit, keyword_match=True)
                for hit in self._store.query_containing(
                    term, embedding=embedding, top_k=_KEYWORD_TOP_K
                )
            )
        pool.sort(key=lambda hit: hit.distance)
        return _merge(pool, [])[:_KEYWORD_POOL]


def _merge(first: list[Hit], second: list[Hit]) -> list[Hit]:
    """去重合併（以 offer_id + text 識別 chunk），保留先到者的順位。"""
    seen: set[tuple] = set()
    merged = []
    for hit in [*first, *second]:
        key = (hit.metadata.get("offer_id"), hit.text)
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)
    return merged
