"""F15 背景補查 job 測試：真 SQLite + 真 ChromaDB，只有 Tavily 與 LLM 注入假件。

端到端那條（test_end_to_end_miss_becomes_retrievable_with_warning）刻意走完整鏈路：
查無寫 miss_log → 補查 job → 抽取入庫 → ingest → 再查一次 → 答案帶 F14 警語。
真網路的部分（Tavily 回不回得出台灣優惠網頁、抽取 prompt 對真實網頁管不管用）
這裡證明不了，需要 TAVILY_API_KEY 手動實跑，見 session-handoff.md。
"""

import json
from datetime import date, datetime, timedelta

from rag.backfill import backfill
from rag.ingest import ingest
from rag.miss_log import init_miss_log, list_misses, record_miss
from rag.pipeline import UNVERIFIED_WARNING, Pipeline
from rag.retriever import Retriever
from rag.vector_store import VectorStore
from scraper.db import init_db, list_offers

NOW = datetime(2026, 8, 23, 12, 0, 0)

NORMALIZED = json.dumps(
    {"brand": "全聯", "product": None, "category": "量販", "official_domain": "pxmart.com.tw"},
    ensure_ascii=False,
)
EXTRACTED = json.dumps(
    {
        "source_type": "credit_card",
        "bank": "玉山銀行",
        "provider": None,
        "title": "全聯刷玉山卡 5% 回饋",
        "content": "全聯門市使用玉山銀行信用卡消費，享 5% 現金回饋，每月上限 300 元。",
        "channel": "全聯",
        "reward_rate": "5%",
    },
    ensure_ascii=False,
)


def fake_complete(replies: list[str]):
    """依呼叫順序吐回覆；用完之後一律吐「抽不出」的空物件。"""
    remaining = list(replies)
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return remaining.pop(0) if remaining else '{"source_type": null}'

    return complete, prompts


def fake_search(results_by_query: dict, calls: list | None = None):
    def search(query: str, include_domains: list[str] | None = None):
        if calls is not None:
            calls.append({"query": query, "include_domains": include_domains})
        return results_by_query.get(query, [])

    return search


def hit(title: str, url: str, content: str):
    from rag.web_search import SearchResult

    return SearchResult(title=title, url=url, content=content)


def seed_miss(conn, query: str, now: datetime = NOW) -> None:
    init_miss_log(conn)
    record_miss(conn, query, now)


class TestBackfill:
    def test_stores_extracted_offer_as_web_unverified(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        seed_miss(conn, "全聯刷什麼卡划算")
        complete, _ = fake_complete([NORMALIZED, EXTRACTED])
        search = fake_search(
            {"全聯 信用卡優惠": [hit("全聯優惠", "https://pxmart.com.tw/a", "玉山 5%")]}
        )

        result = backfill(conn, complete, search, NOW)

        assert (result.processed, result.searched, result.stored) == (1, 1, 1)
        [offer] = list_offers(conn)
        assert offer.trust_tier == "web_unverified"
        assert offer.expires_at == NOW + timedelta(days=7)
        assert offer.title == "全聯刷玉山卡 5% 回饋"

    def test_backfills_entity_onto_miss(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        seed_miss(conn, "全聯刷什麼卡划算")
        complete, _ = fake_complete([NORMALIZED])

        backfill(conn, complete, fake_search({}), NOW)

        assert [m.entity for m in list_misses(conn)] == ["全聯"]

    def test_official_domain_tried_first_then_falls_back(self, tmp_path):
        """官網網域是 LLM 推測的，猜錯要能退回全網搜，不然整個品牌白搜。"""
        conn = init_db(tmp_path / "offers.db")
        seed_miss(conn, "全聯刷什麼卡划算")
        complete, _ = fake_complete([NORMALIZED])
        calls: list = []
        backfill(conn, complete, fake_search({}, calls), NOW)

        assert calls[0]["include_domains"] == ["pxmart.com.tw"]  # 先鎖官網
        assert calls[1]["include_domains"] is None  # 空結果 → 放寬

    def test_no_brand_and_no_category_skips_search(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        seed_miss(conn, "隨便問問")
        complete, _ = fake_complete(['{"brand": null, "product": null, "category": null}'])
        calls: list = []

        result = backfill(conn, complete, fake_search({}, calls), NOW)

        assert (result.searched, result.stored) == (0, 0)
        assert calls == []
        assert [m.entity for m in list_misses(conn)] == [None]  # 下輪可再試

    def test_same_entity_searched_once_per_run(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        init_miss_log(conn)
        record_miss(conn, "全聯刷什麼卡划算", NOW)
        record_miss(conn, "去全聯用哪張卡", NOW)  # 不同問法、同品牌
        complete, _ = fake_complete([NORMALIZED, NORMALIZED])
        calls: list = []

        result = backfill(conn, complete, fake_search({}, calls), NOW)

        assert result.processed == 2
        assert result.searched == 1
        assert {c["query"] for c in calls} == {"全聯 信用卡優惠", "全聯 行動支付 回饋"}

    def test_entity_searched_within_24h_skipped(self, tmp_path):
        """上一輪已經搜過同 entity（miss 記錄在 24h 內）→ 這輪不重搜，省 Tavily 額度。"""
        conn = init_db(tmp_path / "offers.db")
        init_miss_log(conn)
        record_miss(conn, "全聯刷什麼卡", NOW - timedelta(hours=2), entity="全聯")
        record_miss(conn, "全聯有什麼回饋", NOW)
        complete, _ = fake_complete([NORMALIZED])
        calls: list = []

        result = backfill(conn, complete, fake_search({}, calls), NOW)

        assert (result.processed, result.searched) == (1, 0)
        assert calls == []

    def test_extraction_failure_stores_nothing_and_continues(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        seed_miss(conn, "全聯刷什麼卡划算")
        # 抽取回垃圾（非 JSON）→ 整筆丟棄，但 job 不得中斷
        complete, _ = fake_complete([NORMALIZED, "這頁沒有優惠活動"])
        search = fake_search(
            {"全聯 信用卡優惠": [hit("雜訊頁", "https://pxmart.com.tw/x", "無關內容")]}
        )

        result = backfill(conn, complete, search, NOW)

        assert result.stored == 0
        assert list_offers(conn) == []

    def test_search_failure_does_not_abort_run(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        seed_miss(conn, "全聯刷什麼卡划算")
        complete, _ = fake_complete([NORMALIZED])

        def exploding_search(query: str, include_domains=None):
            raise RuntimeError("Tavily 掛了")

        result = backfill(conn, complete, exploding_search, NOW)

        assert (result.processed, result.stored) == (1, 0)  # 吞掉例外，不炸出去

    def test_limit_caps_work_per_run(self, tmp_path):
        conn = init_db(tmp_path / "offers.db")
        init_miss_log(conn)
        for i in range(5):
            record_miss(conn, f"品牌{i}有什麼優惠", NOW)
        complete, _ = fake_complete([NORMALIZED] * 5)

        assert backfill(conn, complete, fake_search({}), NOW, limit=2).processed == 2


def fake_embed(texts: list[str]) -> list[list[float]]:
    """字元命中數當相似度訊號：夠讓「全聯」查詢排到全聯那筆，不必載 torch。"""
    return [[float(t.count("全")), float(t.count("聯")), float(len(t)) / 100] for t in texts]


class FakeGenerator:
    """照 context 回答；不呼叫 LLM，但保留「引用了哪幾筆」這個行為。"""

    def generate(self, question: str, hits: list) -> str:
        return f"依據資料：{hits[0].metadata['title']}"


def test_end_to_end_miss_becomes_retrievable_with_warning(tmp_path):
    """F15 端到端：查無 → miss_log → 補查入庫 → ingest → 再問查得到且帶警語。"""
    conn = init_db(tmp_path / "offers.db")
    store = VectorStore(path=str(tmp_path / "chroma"))
    retriever = Retriever(store=store, embed_query=lambda q: fake_embed([q])[0])

    # 1. 第一次查詢：資料庫空的 → 查無、寫 miss_log、回覆承諾補查
    recorded: list[str] = []

    def record(question: str) -> None:
        recorded.append(question)
        record_miss(conn, question, NOW)

    init_miss_log(conn)
    pipeline = Pipeline(retriever=retriever, generator=FakeGenerator(), record_miss=record)
    first = pipeline.answer("全聯刷什麼卡划算")
    assert "已記下這個問題" in first.answer and "稍後補查" in first.answer
    assert recorded == ["全聯刷什麼卡划算"]
    assert [m.query for m in list_misses(conn)] == ["全聯刷什麼卡划算"]

    # 2. 背景補查 job：正規化 → 網搜 → 抽取 → 入庫
    complete, _ = fake_complete([NORMALIZED, EXTRACTED])
    search = fake_search(
        {"全聯 信用卡優惠": [hit("全聯優惠", "https://pxmart.com.tw/a", "玉山 5%")]}
    )
    assert backfill(conn, complete, search, NOW).stored == 1

    # 3. ingest 進向量庫
    assert ingest(conn, store, fake_embed, today=date(2026, 8, 23)).offers == 1

    # 4. 再問一次同類問題：檢索得到，且回答帶 F14 未驗證警語
    second = pipeline.answer("全聯刷什麼卡划算")
    assert second.answer != first.answer
    assert UNVERIFIED_WARNING in second.answer
    assert "全聯刷玉山卡 5% 回饋" in second.answer.split(UNVERIFIED_WARNING)[1]
    assert [s.trust_tier for s in second.sources] == ["web_unverified"]
