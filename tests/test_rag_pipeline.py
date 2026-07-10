"""RAG pipeline 測試（F4）：retriever / generator / pipeline 全用注入的假件，不打網路。

驗收對應（PRD R4/R5 的 pipeline 層）：
- 有相關資料 → 中文答案 + ≥1 筆來源（title/source_url/valid_to），同 offer 多 chunk 來源去重
- 檢索無結果或相關度太低 → 回「目前資料庫沒有相關優惠資訊。」且 sources=[]，不呼叫 LLM
- generator prompt 必含檢索到的 context 與問題；qwen 系列的 <think> 段要剝掉
"""

import json

from rag.generator import OllamaGenerator
from rag.pipeline import NO_RESULT_ANSWER, Pipeline
from rag.vector_store import Hit


def make_hit(offer_id: int, title: str, distance: float, text: str = "內容") -> Hit:
    return Hit(
        text=text,
        metadata={
            "offer_id": offer_id,
            "title": title,
            "valid_to": "2026-12-31",
            "source_url": f"https://example.com/{offer_id}",
        },
        distance=distance,
    )


class FakeRetriever:
    def __init__(self, hits: list[Hit]):
        self._hits = hits
        self.questions: list[str] = []

    def retrieve(self, question: str, top_k: int = 5) -> list[Hit]:
        self.questions.append(question)
        return self._hits


class TestOllamaGenerator:
    def make_generator(self, reply: str):
        calls: list[dict] = []

        def fake_post(url: str, payload: dict) -> dict:
            calls.append({"url": url, "payload": payload})
            return {"message": {"role": "assistant", "content": reply}}

        gen = OllamaGenerator(
            base_url="http://localhost:11434", model="qwen3:8b", post=fake_post
        )
        return gen, calls

    def test_prompt_contains_context_and_question(self):
        gen, calls = self.make_generator("國泰卡 3% 回饋最划算")
        answer = gen.generate("去好市多刷哪張卡", [make_hit(1, "好市多優惠", 0.1, "國泰 3%")])
        assert answer == "國泰卡 3% 回饋最划算"
        payload = calls[0]["payload"]
        assert payload["model"] == "qwen3:8b"
        assert payload["think"] is False  # qwen3 硬關 thinking：省生成時間（軟開關 /no_think 無效）
        text = json.dumps(payload, ensure_ascii=False)
        assert "國泰 3%" in text and "去好市多刷哪張卡" in text

    def test_strips_think_tags(self):
        gen, _ = self.make_generator("<think>使用者想比較卡片…</think>\n答案在這")
        assert gen.generate("q", [make_hit(1, "t", 0.1)]) == "答案在這"


class TestPipeline:
    def make_pipeline(self, hits: list[Hit], reply: str = "推薦國泰卡"):
        retriever = FakeRetriever(hits)
        generated: list[tuple] = []

        class FakeGenerator:
            def generate(self, question: str, hits: list[Hit]) -> str:
                generated.append((question, hits))
                return reply

        return Pipeline(retriever=retriever, generator=FakeGenerator()), generated

    def test_answer_with_deduped_sources(self):
        hits = [
            make_hit(1, "好市多優惠", 0.10),
            make_hit(1, "好市多優惠", 0.12),  # 同優惠第二個 chunk
            make_hit(2, "量販店優惠", 0.20),
        ]
        pipeline, generated = self.make_pipeline(hits)
        result = pipeline.answer("去好市多刷哪張卡最划算")
        assert result.answer == "推薦國泰卡"
        assert [s.title for s in result.sources] == ["好市多優惠", "量販店優惠"]
        assert result.sources[0].source_url == "https://example.com/1"
        assert result.sources[0].valid_to == "2026-12-31"
        assert len(generated) == 1

    def test_no_hits_returns_fallback_without_calling_llm(self):
        pipeline, generated = self.make_pipeline([])
        result = pipeline.answer("火星旅遊有什麼優惠")
        assert result.answer == NO_RESULT_ANSWER
        assert result.sources == []
        assert generated == []  # 沒 context 不呼叫 LLM，從源頭防幻覺（R5）

    def test_keyword_match_bypasses_distance_threshold(self):
        """關鍵詞精確命中是高信心證據，不吃向量門檻（好市多正解 0.415 > 0.4 的教訓）。"""
        from dataclasses import replace

        keyword_hit = replace(make_hit(1, "優食好市多專區享2%回饋", 0.45), keyword_match=True)
        pipeline, generated = self.make_pipeline([keyword_hit])
        result = pipeline.answer("去好市多刷哪張卡最划算")
        assert result.answer == "推薦國泰卡"
        assert len(generated) == 1

    def test_low_relevance_hits_filtered_out(self):
        pipeline, generated = self.make_pipeline([make_hit(1, "無關優惠", 0.95)])
        result = pipeline.answer("火星旅遊有什麼優惠")
        assert result.answer == NO_RESULT_ANSWER
        assert result.sources == []
        assert generated == []

    def test_llm_no_info_reply_clears_sources(self):
        """檢索過門檻但 LLM 判定資料無關 → 回固定句且 sources 清空（R5 第二道防線）。"""
        pipeline, _ = self.make_pipeline(
            [make_hit(1, "擦邊優惠", 0.30)], reply="目前資料庫沒有相關優惠資訊。"
        )
        result = pipeline.answer("火星旅遊有什麼優惠")
        assert result.answer == NO_RESULT_ANSWER
        assert result.sources == []

    def test_generation_context_capped(self):
        """top_k 拉大讓正解進得來，但生成端 context 有上限（模型 num_ctx 有限）。"""
        hits = [make_hit(i, f"優惠{i}", 0.10 + i * 0.001) for i in range(20)]
        pipeline, generated = self.make_pipeline(hits)
        pipeline.answer("問題")
        [(_, hits_for_llm)] = generated
        assert len(hits_for_llm) == 12

    def test_context_deduped_by_offer_before_cap(self):
        """同一優惠多個 chunk 只留最相關的一個——多樣性讓沉在後段的正解擠得進 context。"""
        # 3 個優惠各 4 個 chunk 佔滿前 12 名，第 13 名是第 4 個優惠（模擬好市多情境）
        hits = []
        for rank in range(12):
            hits.append(make_hit(rank % 3, f"優惠{rank % 3}", 0.10 + rank * 0.001))
        hits.append(make_hit(99, "沉底正解", 0.115))
        pipeline, generated = self.make_pipeline(hits)
        pipeline.answer("問題")
        [(_, hits_for_llm)] = generated
        assert len(hits_for_llm) == 4  # 3 個去重後的優惠 + 沉底正解
        assert [h.metadata["offer_id"] for h in hits_for_llm] == [0, 1, 2, 99]
        # 每個優惠留的是它 distance 最小的那個 chunk
        assert hits_for_llm[0].distance == 0.10

    def test_sources_capped_at_five(self):
        hits = [make_hit(i, f"優惠{i}", 0.10 + i * 0.001) for i in range(10)]
        pipeline, _ = self.make_pipeline(hits)
        result = pipeline.answer("問題")
        assert len(result.sources) == 5
