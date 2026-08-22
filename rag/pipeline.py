"""RAG pipeline：檢索 → 相關度過濾 → 生成 → 答案 + 來源。

R5 防幻覺從源頭做：檢索無結果或相關度不足 → 直接回固定句，不呼叫 LLM。
來源以 offer_id 去重（一優惠多 chunk 只列一次），保留檢索排序。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from config.settings import Settings
from rag.vector_store import Hit

NO_RESULT_ANSWER = "目前資料庫沒有相關優惠資訊。"
# F14：分層信任的落地點——引用網搜補來的資料時，警語與被標示的條目一起附在回答末尾
UNVERIFIED_WARNING = "⚠️ 來自網路搜尋、未經驗證，使用前請確認官網"
# e5-small 的 distance 分布擠（相關 0.10 vs 無關 0.11~0.16），門檻只當 sanity check；
# 無關問題的真正防線是 LLM 拒答 + 清 sources（見 answer()）。實測記錄見 DECISIONS D6
DEFAULT_MAX_DISTANCE = 0.4
# 檢索 top_k 拉大讓正解擠得進來（實測正解可能排到 16 名），但生成端 context 有限
MAX_CONTEXT_CHUNKS = 12
MAX_SOURCES = 5


@dataclass(frozen=True)
class Source:
    title: str
    source_url: str
    valid_to: str | None
    # 舊 chunk（F12 之前入庫）metadata 沒這個欄位，預設 verified 才不會誤標警語
    trust_tier: str = "verified"


@dataclass(frozen=True)
class Answer:
    answer: str
    sources: list[Source]


class SupportsRetrieve(Protocol):
    def retrieve(self, question: str, top_k: int = ...) -> list[Hit]: ...


class SupportsGenerate(Protocol):
    def generate(self, question: str, hits: list[Hit]) -> str: ...


class Pipeline:
    def __init__(
        self,
        retriever: SupportsRetrieve,
        generator: SupportsGenerate,
        max_distance: float = DEFAULT_MAX_DISTANCE,
        record_miss: Callable[[str], None] | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._max_distance = max_distance
        self._record_miss = record_miss

    def answer(self, question: str) -> Answer:
        relevant = [
            hit
            for hit in self._retriever.retrieve(question)
            if hit.keyword_match or hit.distance <= self._max_distance
        ]
        # 一優惠只留最相關的 chunk，再依來源 round-robin 重排：避免 keyword 命中率高的
        # 單一銀行（如台新）壟斷 context 前段，讓答案與 sources 涵蓋多家（F10）
        hits = _diversify_by_source(_dedupe_by_offer(relevant))[:MAX_CONTEXT_CHUNKS]
        if not hits:
            return self._no_result(question)
        reply = self._generator.generate(question, hits)
        if "目前資料庫沒有相關優惠" in reply:
            # 第二道防線：檢索過門檻但 LLM 判定資料答不了 → 不要附誤導的來源（R5）
            return self._no_result(question)
        cited = _sources(hits)
        # 警語看的是整個 context（未截斷）：LLM 可能引用第 6 名以後、列不進 sources 的
        # 未驗證資料，只看截斷後的清單會漏標
        return Answer(answer=_append_warning(reply, cited), sources=cited[:MAX_SOURCES])

    def _no_result(self, question: str) -> Answer:
        """兩條拒答出口共用：回固定句，順手把 query 記進 miss_log（F11）。"""
        if self._record_miss is not None:
            self._record_miss(question)
        return Answer(answer=NO_RESULT_ANSWER, sources=[])


class SupportsAnswer(Protocol):
    """API 層依賴的最小介面（測試注入 fake 用）。"""

    def answer(self, question: str) -> Answer: ...


class SupportsStats(Protocol):
    """/health 與 503 判斷所需的知識庫狀態（VectorStore 天然滿足）。"""

    def count(self) -> int: ...

    def offers_count(self) -> int: ...

    def last_ingest_at(self) -> str | None: ...


@dataclass(frozen=True)
class RagRuntime:
    """組裝完成的 RAG 執行環境：api/ 只透過這兩個介面碰 rag 層。

    pipeline 與 stats 綁成一包注入，避免只換一半（stats 留 None 會在請求時才炸）。
    """

    pipeline: SupportsAnswer
    stats: SupportsStats


def build_default(settings: Settings) -> RagRuntime:
    """依設定組裝正式環境的 pipeline（CLI 與 API 共用的組裝入口）。"""
    from rag.embedder import Embedder  # 延後 import：載 torch 很慢
    from rag.generator import build_generator
    from rag.miss_log import build_miss_recorder
    from rag.retriever import Retriever
    from rag.vector_store import VectorStore

    store = VectorStore(path=settings.chroma_path)
    retriever = Retriever(store=store, embed_query=Embedder(settings.embedding_model).embed_query)
    generator = build_generator(settings)  # R6：provider 切換 + 缺金鑰 fail fast
    pipeline = Pipeline(
        retriever=retriever,
        generator=generator,
        record_miss=build_miss_recorder(settings.database_path),  # F11：查無留紀錄
    )
    return RagRuntime(pipeline=pipeline, stats=store)


def _append_warning(reply: str, cited: list[Source]) -> str:
    """引用未驗證資料時附警語並逐條列出（F14）。全 verified 時原字串原封不動回傳。

    只列 web_unverified 的標題——混合來源時 verified 條目不該被連坐標示。
    """
    unverified = [s.title for s in cited if s.trust_tier == "web_unverified"]
    if not unverified:
        return reply
    return f"{reply}\n\n{UNVERIFIED_WARNING}：{'、'.join(unverified)}"


def _dedupe_by_offer(hits: list[Hit]) -> list[Hit]:
    """每個 offer 只留 distance 最小的 chunk，保留原排序（retriever 已依 distance 升冪）。"""
    seen: set[int] = set()
    unique = []
    for hit in hits:
        offer_id = hit.metadata["offer_id"]
        if offer_id in seen:
            continue
        seen.add(offer_id)
        unique.append(hit)
    return unique


def _diversify_by_source(hits: list[Hit]) -> list[Hit]:
    """依來源（source_url host）做 stable round-robin 重排：各來源輪流貢獻一筆。

    只重排傳入的候選（呼叫端已過相關度門檻），不引入新資料。單一來源時等同不動；
    每輪先取各來源最相關的一筆，故整體最相關者仍在最前，各來源內部順序（相關度）不變。
    """
    groups: dict[str, list[Hit]] = {}
    for hit in hits:
        key = urlparse(hit.metadata.get("source_url", "")).netloc
        groups.setdefault(key, []).append(hit)
    ordered: list[Hit] = []
    for rank in range(max((len(g) for g in groups.values()), default=0)):
        for group in groups.values():
            if rank < len(group):
                ordered.append(group[rank])
    return ordered


def _sources(hits: list[Hit]) -> list[Source]:
    seen: set[int] = set()
    sources = []
    for hit in hits:
        offer_id = hit.metadata["offer_id"]
        if offer_id in seen:
            continue
        seen.add(offer_id)
        sources.append(
            Source(
                title=hit.metadata.get("title", ""),
                source_url=hit.metadata["source_url"],
                valid_to=hit.metadata.get("valid_to") or None,
                trust_tier=hit.metadata.get("trust_tier", "verified"),
            )
        )
    return sources
