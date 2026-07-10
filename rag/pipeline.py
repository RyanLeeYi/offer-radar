"""RAG pipeline：檢索 → 相關度過濾 → 生成 → 答案 + 來源。

R5 防幻覺從源頭做：檢索無結果或相關度不足 → 直接回固定句，不呼叫 LLM。
來源以 offer_id 去重（一優惠多 chunk 只列一次），保留檢索排序。
"""

from dataclasses import dataclass
from typing import Protocol

from config.settings import Settings
from rag.vector_store import Hit

NO_RESULT_ANSWER = "目前資料庫沒有相關優惠資訊。"
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
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._max_distance = max_distance

    def answer(self, question: str) -> Answer:
        relevant = [
            hit
            for hit in self._retriever.retrieve(question)
            if hit.keyword_match or hit.distance <= self._max_distance
        ]
        # 一優惠只留最相關的 chunk：省下的 context 讓沉在後段的其他優惠擠得進來
        hits = _dedupe_by_offer(relevant)[:MAX_CONTEXT_CHUNKS]
        if not hits:
            return Answer(answer=NO_RESULT_ANSWER, sources=[])
        reply = self._generator.generate(question, hits)
        if "目前資料庫沒有相關優惠" in reply:
            # 第二道防線：檢索過門檻但 LLM 判定資料答不了 → 不要附誤導的來源（R5）
            return Answer(answer=NO_RESULT_ANSWER, sources=[])
        return Answer(answer=reply, sources=_sources(hits)[:MAX_SOURCES])


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
    from rag.generator import OllamaGenerator
    from rag.retriever import Retriever
    from rag.vector_store import VectorStore

    store = VectorStore(path=settings.chroma_path)
    retriever = Retriever(store=store, embed_query=Embedder(settings.embedding_model).embed_query)
    generator = OllamaGenerator(base_url=settings.ollama_base_url, model=settings.ollama_model)
    return RagRuntime(pipeline=Pipeline(retriever=retriever, generator=generator), stats=store)


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
            )
        )
    return sources
