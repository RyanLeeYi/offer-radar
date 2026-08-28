"""ollama 健康預檢測試（F25）：查詢前快速判定 provider 能不能即時出 token。

驗收對應：
- /api/ps 連不上 → ProviderUnavailable（可讀訊息說 ollama 連不上）
- 模型未載入 → 冷啟動放行，不做探測（不得誤殺冷啟動）
- 模型已載入但探測逾時／失敗 → ProviderUnavailable（點出已載入卻吐不出 token）
- 正式組裝的 generator 每次 generate 前跑預檢；未注入 check 的建構路徑行為不變
- API 層把 ProviderUnavailable 轉成 504 + 例外訊息，不是 500、不空等
"""

import time

import pytest
import requests
from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from rag.generator import OllamaGenerator, build_generator
from rag.llm_provider import (
    HEALTH_TIMEOUT,
    PS_TIMEOUT,
    ProviderUnavailable,
    check_ollama,
)
from rag.pipeline import Pipeline, RagRuntime
from rag.vector_store import Hit
from tests.test_api import FakeStats

BASE_URL = "http://localhost:11434"
MODEL = "qwen3:8b"

HITS = [
    Hit(
        text="好市多刷卡 2% 回饋",
        metadata={"offer_id": 1, "source_url": "https://example.com/a", "title": "A"},
        distance=0.1,
    )
]


class _StubRetriever:
    """固定回同一批 hits——本檔關心的是 generator 之後的事，檢索只需要不擋路。"""

    def __init__(self, hits: list[Hit]) -> None:
        self._hits = hits

    def retrieve(self, question: str, top_k: int = 5) -> list[Hit]:
        return self._hits


def _ps(*models: str):
    """假 GET：回 /api/ps 形狀（ollama 的 model 欄帶 tag，name 同值）。"""

    def get(url: str, timeout: float) -> dict:
        assert url.endswith("/api/ps")
        return {"models": [{"name": m, "model": m} for m in models]}

    return get


def _post_ok(url: str, payload: dict, timeout: float) -> dict:
    return {"response": "好"}


def test_ps_unreachable_raises_readable_error():
    def get(url: str, timeout: float) -> dict:
        raise requests.ConnectionError("connection refused")

    with pytest.raises(ProviderUnavailable) as exc:
        check_ollama(BASE_URL, MODEL, get=get, post=_post_ok)
    assert "ollama" in str(exc.value)


def test_model_not_loaded_is_cold_start_and_skips_probe():
    """冷啟動本來就慢（8B 實測約 24 秒），不能因此判死——也不該浪費一次探測。"""
    probes: list[str] = []

    def post(url: str, payload: dict, timeout: float) -> dict:
        probes.append(url)
        return {}

    check_ollama(BASE_URL, MODEL, get=_ps("other-model:7b"), post=post)
    assert probes == []


def test_loaded_but_probe_times_out_raises():
    def post(url: str, payload: dict, timeout: float) -> dict:
        raise requests.Timeout("read timeout")

    with pytest.raises(ProviderUnavailable) as exc:
        check_ollama(BASE_URL, MODEL, get=_ps(MODEL), post=post)
    message = str(exc.value)
    assert MODEL in message and "CPU" in message


def test_loaded_and_probe_fails_raises():
    def post(url: str, payload: dict, timeout: float) -> dict:
        raise requests.HTTPError("500 server error")

    with pytest.raises(ProviderUnavailable):
        check_ollama(BASE_URL, MODEL, get=_ps(MODEL), post=post)


def test_loaded_and_healthy_passes_with_one_token_probe():
    seen: list[dict] = []

    def post(url: str, payload: dict, timeout: float) -> dict:
        seen.append({"url": url, "payload": payload, "timeout": timeout})
        return {"response": "好"}

    check_ollama(BASE_URL, MODEL, get=_ps(MODEL), post=post)
    assert seen[0]["url"].endswith("/api/generate")
    assert seen[0]["payload"]["options"]["num_predict"] == 1
    assert seen[0]["timeout"] <= 5.0


def test_generator_runs_check_before_generating():
    calls: list[str] = []

    def check() -> None:
        calls.append("check")
        raise ProviderUnavailable("模型忙不過來")

    generator = OllamaGenerator(
        base_url=BASE_URL,
        model=MODEL,
        post=lambda url, payload: calls.append("post") or {"message": {"content": "x"}},
        check=check,
    )
    with pytest.raises(ProviderUnavailable):
        generator.generate("好市多", HITS)
    assert calls == ["check"]  # 預檢擋下就不打真的 chat


def test_generator_without_check_keeps_old_behaviour():
    generator = OllamaGenerator(
        base_url=BASE_URL, model=MODEL, post=lambda url, payload: {"message": {"content": "答案"}}
    )
    assert generator.generate("好市多", HITS) == "答案"


def test_build_generator_wires_the_real_check():
    generator = build_generator(Settings(llm_provider="ollama"))
    assert generator._check is not None


class BoomPipeline:
    def answer(self, question: str):
        raise ProviderUnavailable("ollama 模型已載入但無法即時產出 token")


def test_api_returns_504_with_readable_message():
    app = create_app(runtime=RagRuntime(pipeline=BoomPipeline(), stats=FakeStats()), query_timeout=30.0)
    response = TestClient(app).post("/query", json={"question": "好市多刷哪張卡"})
    assert response.status_code == 504
    assert response.json()["error"] == "ollama 模型已載入但無法即時產出 token"


def test_real_chain_surfaces_504_without_waiting_for_timeout():
    """整條真鏈路：OllamaGenerator → Pipeline → API。

    分開的假件測試證明不了最要命的那件事——``Pipeline.answer`` 沒有把
    ProviderUnavailable 吞掉當成拒答。順帶釘住 F25 的重點：回應時間跟
    query_timeout 無關（這裡給 30 秒，實際應該立刻回）。
    """
    chat_calls: list[str] = []

    def check() -> None:
        raise ProviderUnavailable("ollama 模型 qwen3:8b 已載入，卻無法即時產出 token")

    generator = OllamaGenerator(
        base_url=BASE_URL,
        model=MODEL,
        post=lambda url, payload: chat_calls.append(url) or {"message": {"content": "x"}},
        check=check,
    )
    pipeline = Pipeline(retriever=_StubRetriever(HITS), generator=generator)
    app = create_app(
        runtime=RagRuntime(pipeline=pipeline, stats=FakeStats()), query_timeout=30.0
    )

    started = time.monotonic()
    response = TestClient(app).post("/query", json={"question": "好市多刷哪張卡"})
    elapsed = time.monotonic() - started

    assert response.status_code == 504
    assert response.json()["error"].startswith("ollama 模型 qwen3:8b 已載入")
    assert chat_calls == []  # 預檢擋下就沒打真的 /api/chat
    assert elapsed < 5.0  # 沒有空等 query_timeout


def test_timeout_budgets_keep_their_margins():
    """兩個預算都是校準過的數字，不是隨手填的——被「順手調小」時要有東西會紅。

    HEALTH_TIMEOUT 由 acceptance 指定為 5 秒。PS_TIMEOUT 必須明顯高於
    localhost 在 Windows 上的 IPv6 fallback 成本（實測 2.0 秒／次），否則主機
    一忙就誤報「連不上 ollama」——而主機忙正是這道預檢存在的理由。
    F26 把預設 base_url 改成 127.0.0.1 後這條餘裕仍要留著：.env 可以覆寫回 localhost。
    """
    assert HEALTH_TIMEOUT == 5.0
    assert PS_TIMEOUT >= 2.0 * 3  # 至少 3 倍餘裕
