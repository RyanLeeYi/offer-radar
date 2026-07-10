"""FastAPI /query + /health 測試（PRD R4+R5 邊界）：httpx TestClient + 假 pipeline 注入。

驗收對應：
- 200 含 answer + sources（title/source_url/valid_to）
- 無關問題固定句 + sources=[]（pipeline 已保證，API 原樣透傳）
- 缺 question / 空字串 / 超 500 字 → 422
- 未建庫 → 503 {"error": "知識庫尚未建立"}
- LLM 逾時 → 504 {"error": "LLM 回應逾時，請稍後再試"}（API 層 30 秒契約，測試注入短逾時）
"""

import time

from fastapi.testclient import TestClient

from api.main import create_app
from rag.pipeline import NO_RESULT_ANSWER, Answer, RagRuntime, Source

ANSWER = Answer(
    answer="推薦 Costco 聯名卡，好市多消費 2% 回饋。",
    sources=[
        Source(title="Costco 聯名卡", source_url="https://example.com/costco", valid_to="2026-12-31"),
        Source(title="無期限優惠", source_url="https://example.com/forever", valid_to=None),
    ],
)


class FakePipeline:
    def __init__(self, result: Answer = ANSWER, delay: float = 0.0) -> None:
        self._result = result
        self._delay = delay
        self.calls: list[str] = []

    def answer(self, question: str) -> Answer:
        self.calls.append(question)
        if self._delay:
            time.sleep(self._delay)
        return self._result


class FakeStats:
    def __init__(self, chunks: int = 10, offers: int = 3, last_ingest: str | None = "2026-07-10T22:00:00+08:00") -> None:
        self._chunks = chunks
        self._offers = offers
        self._last_ingest = last_ingest

    def count(self) -> int:
        return self._chunks

    def offers_count(self) -> int:
        return self._offers

    def last_ingest_at(self) -> str | None:
        return self._last_ingest


def make_client(pipeline=None, stats=None, query_timeout: float = 30.0) -> TestClient:
    # runtime 一包注入：pipeline/stats 必成對，不會只換一半（partial injection 曾是 bug）
    runtime = RagRuntime(pipeline=pipeline or FakePipeline(), stats=stats or FakeStats())
    app = create_app(runtime=runtime, query_timeout=query_timeout)
    return TestClient(app)


def test_query_returns_answer_and_sources():
    client = make_client()
    response = client.post("/query", json={"question": "去好市多刷哪張卡最划算"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("推薦 Costco")
    assert body["sources"] == [
        {"title": "Costco 聯名卡", "source_url": "https://example.com/costco", "valid_to": "2026-12-31"},
        {"title": "無期限優惠", "source_url": "https://example.com/forever", "valid_to": None},
    ]


def test_query_no_result_passthrough():
    client = make_client(pipeline=FakePipeline(result=Answer(answer=NO_RESULT_ANSWER, sources=[])))
    response = client.post("/query", json={"question": "火星旅遊有什麼優惠"})
    assert response.status_code == 200
    body = response.json()
    assert "目前資料庫沒有相關優惠" in body["answer"]
    assert body["sources"] == []


def test_query_missing_question_422():
    assert make_client().post("/query", json={}).status_code == 422


def test_query_empty_question_422():
    assert make_client().post("/query", json={"question": ""}).status_code == 422


def test_query_over_500_chars_422():
    assert make_client().post("/query", json={"question": "問" * 501}).status_code == 422


def test_query_exactly_500_chars_ok():
    assert make_client().post("/query", json={"question": "問" * 500}).status_code == 200


def test_query_before_ingest_503_and_skips_llm():
    pipeline = FakePipeline()
    client = make_client(pipeline=pipeline, stats=FakeStats(chunks=0, offers=0, last_ingest=None))
    response = client.post("/query", json={"question": "去好市多刷哪張卡最划算"})
    assert response.status_code == 503
    assert response.json() == {"error": "知識庫尚未建立"}
    assert pipeline.calls == []  # 未建庫不該打 LLM


def test_query_timeout_504():
    client = make_client(pipeline=FakePipeline(delay=0.5), query_timeout=0.05)
    response = client.post("/query", json={"question": "去好市多刷哪張卡最划算"})
    assert response.status_code == 504
    assert response.json() == {"error": "LLM 回應逾時，請稍後再試"}


def test_health_reports_counts():
    client = make_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "offers_count": 3,
        "last_ingest_at": "2026-07-10T22:00:00+08:00",
    }


def test_health_before_ingest_still_ok():
    client = make_client(stats=FakeStats(chunks=0, offers=0, last_ingest=None))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "offers_count": 0, "last_ingest_at": None}
