"""RAG pipeline 測試（F4）：retriever / generator / pipeline 全用注入的假件，不打網路。

驗收對應（PRD R4/R5 的 pipeline 層）：
- 有相關資料 → 中文答案 + ≥1 筆來源（title/source_url/valid_to），同 offer 多 chunk 來源去重
- 檢索無結果或相關度太低 → 回「目前資料庫沒有相關優惠資訊。」且 sources=[]，不呼叫 LLM
- generator prompt 必含檢索到的 context 與問題；qwen 系列的 <think> 段要剝掉
"""

import json
from urllib.parse import urlparse

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


class TestOpenAIGenerator:
    def make_generator(self, reply: str):
        from rag.generator import OpenAIGenerator

        calls: list[dict] = []

        def fake_complete(model: str, messages: list[dict]) -> str:
            calls.append({"model": model, "messages": messages})
            return reply

        return OpenAIGenerator(model="gpt-4o-mini", complete=fake_complete), calls

    def test_prompt_contains_context_and_question(self):
        gen, calls = self.make_generator("國泰卡 3% 回饋最划算")
        answer = gen.generate("去好市多刷哪張卡", [make_hit(1, "好市多優惠", 0.1, "國泰 3%")])
        assert answer == "國泰卡 3% 回饋最划算"
        assert calls[0]["model"] == "gpt-4o-mini"
        text = json.dumps(calls[0]["messages"], ensure_ascii=False)
        assert "國泰 3%" in text and "去好市多刷哪張卡" in text

    def test_shares_prompt_recipe_with_ollama(self):
        """兩個 generator 對同輸入組出的 user content 一致——prompt 配方單一事實來源。"""
        hits = [make_hit(1, "好市多優惠", 0.1, "國泰 3%")]
        openai_gen, oai_calls = self.make_generator("x")
        openai_gen.generate("去好市多刷哪張卡", hits)
        ollama_gen, olm_calls = TestOllamaGenerator().make_generator("x")
        ollama_gen.generate("去好市多刷哪張卡", hits)
        oai_user = [m for m in oai_calls[0]["messages"] if m["role"] == "user"][-1]["content"]
        olm_user = olm_calls[0]["payload"]["messages"][-1]["content"]
        assert oai_user == olm_user


class TestBuildGenerator:
    def _settings(self, **overrides):
        from config.settings import Settings

        base = {"llm_provider": "ollama", "openai_api_key": "", "openai_model": "gpt-4o-mini"}
        return Settings(**{**base, **overrides})

    def test_ollama_provider_builds_ollama_generator(self):
        from rag.generator import OllamaGenerator, build_generator

        assert isinstance(build_generator(self._settings()), OllamaGenerator)

    def test_openai_provider_with_key_builds_openai_generator(self):
        from rag.generator import OpenAIGenerator, build_generator

        gen = build_generator(self._settings(llm_provider="openai", openai_api_key="sk-test"))
        assert isinstance(gen, OpenAIGenerator)

    def test_openai_provider_without_key_fails_fast(self):
        from rag.generator import build_generator

        try:
            build_generator(self._settings(llm_provider="openai", openai_api_key=""))
        except ValueError as error:
            assert "OPENAI_API_KEY" in str(error)
        else:
            raise AssertionError("缺 OPENAI_API_KEY 時應在建構期即 raise，不得延到查詢時")

    def test_unknown_provider_fails_fast(self):
        from rag.generator import build_generator

        try:
            build_generator(self._settings(llm_provider="gemini"))
        except ValueError as error:
            assert "gemini" in str(error)
        else:
            raise AssertionError("未知 provider 應 fail fast")


def build_pipeline(hits: list[Hit], reply: str = "推薦國泰卡", record_miss=None):
    """組一條全假件的 pipeline，回 (pipeline, 生成呼叫記錄)。"""
    generated: list[tuple] = []

    class FakeGenerator:
        def generate(self, question: str, hits: list[Hit]) -> str:
            generated.append((question, hits))
            return reply

    pipeline = Pipeline(
        retriever=FakeRetriever(hits), generator=FakeGenerator(), record_miss=record_miss
    )
    return pipeline, generated


class TestPipeline:
    def make_pipeline(self, hits: list[Hit], reply: str = "推薦國泰卡", record_miss=None):
        return build_pipeline(hits, reply, record_miss)

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
        pipeline, _ = build_pipeline(
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
        pipeline, _ = build_pipeline(hits)
        result = pipeline.answer("問題")
        assert len(result.sources) == 5


class TestSourceDiversity:
    """F10：單一來源不得壟斷 context/sources，dedupe 後做來源 round-robin 重排。"""

    def _hit(self, offer_id: int, distance: float, host: str) -> Hit:
        return Hit(
            text="內容",
            metadata={
                "offer_id": offer_id,
                "title": f"優惠{offer_id}",
                "valid_to": "2026-12-31",
                "source_url": f"https://{host}/{offer_id}",
            },
            distance=distance,
        )

    def _hosts(self, hits: list[Hit]) -> list[str]:
        return [urlparse(h.metadata["source_url"]).netloc for h in hits]

    def test_round_robin_interleaves_sources(self):
        from rag.pipeline import _diversify_by_source

        # 台新 3 筆最相關（會壟斷）+ 國泰 1 + 富邦 1
        hits = [
            self._hit(1, 0.10, "taishin"),
            self._hit(2, 0.12, "taishin"),
            self._hit(3, 0.14, "taishin"),
            self._hit(4, 0.20, "cathay"),
            self._hit(5, 0.22, "fubon"),
        ]
        out = _diversify_by_source(hits)
        assert set(self._hosts(out)[:3]) == {"taishin", "cathay", "fubon"}  # 前3涵蓋3家
        assert out[0].metadata["offer_id"] == 1  # 最相關的第一筆不變
        taishin = [h.metadata["offer_id"] for h in out if "taishin" in h.metadata["source_url"]]
        assert taishin == [1, 2, 3]  # 同來源內部順序（相關度）保持

    def test_single_source_unchanged(self):
        from rag.pipeline import _diversify_by_source

        hits = [self._hit(i, 0.10 + i * 0.01, "taishin") for i in range(4)]
        out = _diversify_by_source(hits)
        assert [h.metadata["offer_id"] for h in out] == [0, 1, 2, 3]  # 單一來源不重排

    def test_pipeline_sources_span_multiple_banks(self):
        # 台新 8 筆壟斷候選（都最相關）+ 國泰 2 + 富邦 2，全部通過門檻
        hits = (
            [self._hit(i, 0.10 + i * 0.001, "taishin") for i in range(8)]
            + [self._hit(100 + i, 0.15 + i * 0.001, "cathay") for i in range(2)]
            + [self._hit(200 + i, 0.16 + i * 0.001, "fubon") for i in range(2)]
        )

        class FakeGen:
            def generate(self, question: str, hits: list[Hit]) -> str:
                return "推薦"

        pipeline = Pipeline(retriever=FakeRetriever(hits), generator=FakeGen())
        result = pipeline.answer("網購優惠")
        hosts = {urlparse(s.source_url).netloc for s in result.sources}
        assert len(hosts) >= 3  # top5 不再被台新壟斷


class TestMissRecording:
    """F11：兩條拒答路徑都要把 query 原文交給 miss_log，有答案時不記。"""

    def test_no_hits_records_miss(self):
        recorded: list[str] = []
        pipeline, _ = build_pipeline([], record_miss=recorded.append)
        assert pipeline.answer("火星旅遊有什麼優惠").answer == NO_RESULT_ANSWER
        assert recorded == ["火星旅遊有什麼優惠"]

    def test_low_relevance_records_miss(self):
        recorded: list[str] = []
        pipeline, _ = build_pipeline([make_hit(1, "無關優惠", 0.95)], record_miss=recorded.append)
        assert pipeline.answer("火星旅遊有什麼優惠").answer == NO_RESULT_ANSWER
        assert recorded == ["火星旅遊有什麼優惠"]

    def test_llm_refusal_records_miss(self):
        """檢索過門檻但 LLM 拒答也是查無——只補第一條路徑會漏掉這個出口。"""
        recorded: list[str] = []
        pipeline, _ = build_pipeline(
            [make_hit(1, "擦邊優惠", 0.30)],
            reply="目前資料庫沒有相關優惠資訊。",
            record_miss=recorded.append,
        )
        assert pipeline.answer("火星旅遊有什麼優惠").answer == NO_RESULT_ANSWER
        assert recorded == ["火星旅遊有什麼優惠"]

    def test_successful_answer_records_nothing(self):
        recorded: list[str] = []
        pipeline, _ = build_pipeline([make_hit(1, "好市多優惠", 0.10)], record_miss=recorded.append)
        assert pipeline.answer("去好市多刷哪張卡").answer == "推薦國泰卡"
        assert recorded == []

    def test_without_recorder_behaviour_unchanged(self):
        """沒注入 recorder（既有測試與 CLI）→ 行為與現狀完全相同。"""
        pipeline, generated = build_pipeline([])
        result = pipeline.answer("火星旅遊有什麼優惠")
        assert (result.answer, result.sources, generated) == (NO_RESULT_ANSWER, [], [])


class TestUnverifiedWarning:
    """F14：引用 web_unverified 資料的回答必附警語；全 verified 時行為不變。"""

    def _hit(self, offer_id: int, title: str, trust_tier: str) -> Hit:
        from dataclasses import replace

        hit = make_hit(offer_id, title, 0.10 + offer_id * 0.001)
        return replace(hit, metadata={**hit.metadata, "trust_tier": trust_tier})

    def test_unverified_source_appends_warning(self):
        from rag.pipeline import UNVERIFIED_WARNING

        pipeline, _ = build_pipeline([self._hit(1, "網搜好市多優惠", "web_unverified")])
        result = pipeline.answer("去好市多刷哪張卡")
        assert result.answer.startswith("推薦國泰卡")
        assert UNVERIFIED_WARNING in result.answer
        assert "網搜好市多優惠" in result.answer.split(UNVERIFIED_WARNING)[1]

    def test_all_verified_answer_byte_identical(self):
        """全部來自 verified → 回答與現狀一模一樣（不多一個字元）。"""
        pipeline, _ = build_pipeline([self._hit(1, "台新優惠", "verified")])
        assert pipeline.answer("問題").answer == "推薦國泰卡"

    def test_missing_trust_tier_treated_as_verified(self):
        """舊 chunk（F12 之前入庫）metadata 沒有 trust_tier → 不得誤標警語。"""
        pipeline, _ = build_pipeline([make_hit(1, "舊資料優惠", 0.10)])
        assert pipeline.answer("問題").answer == "推薦國泰卡"

    def test_mixed_sources_marks_only_unverified(self):
        from rag.pipeline import UNVERIFIED_WARNING

        pipeline, _ = build_pipeline(
            [
                self._hit(1, "台新官網優惠", "verified"),
                self._hit(2, "網搜全聯優惠", "web_unverified"),
            ]
        )
        result = pipeline.answer("問題")
        listed = result.answer.split(UNVERIFIED_WARNING)[1]
        assert "網搜全聯優惠" in listed
        assert "台新官網優惠" not in listed  # verified 條目不得被連坐標示

    def test_sources_carry_trust_tier(self):
        pipeline, _ = build_pipeline(
            [
                self._hit(1, "台新官網優惠", "verified"),
                self._hit(2, "網搜全聯優惠", "web_unverified"),
            ]
        )
        tiers = {s.title: s.trust_tier for s in pipeline.answer("問題").sources}
        assert tiers == {"台新官網優惠": "verified", "網搜全聯優惠": "web_unverified"}

    def test_no_result_answer_has_no_warning(self):
        from rag.pipeline import UNVERIFIED_WARNING

        pipeline, _ = build_pipeline([])
        assert UNVERIFIED_WARNING not in pipeline.answer("火星旅遊有什麼優惠").answer

    def test_prompt_marks_unverified_blocks(self):
        """抽取端已丟棄不合格資料，但 LLM 仍要知道哪幾塊未經驗證才能逐條標示。"""
        from rag.generator import build_user_content

        content = build_user_content(
            "問題",
            [
                self._hit(1, "台新官網優惠", "verified"),
                self._hit(2, "網搜全聯優惠", "web_unverified"),
            ],
        )
        assert "【資料 1】" in content
        assert "【資料 2｜未經驗證】" in content


class TestBackfillNotice:
    """F15：查無回覆要告知已記下、稍後補查（不推播，下次再問才搜得到）。"""

    def test_no_result_answer_promises_backfill(self):
        assert "已記下這個問題" in NO_RESULT_ANSWER
        assert "稍後補查" in NO_RESULT_ANSWER

    def test_both_refusal_paths_use_same_notice(self):
        """檢索無結果與 LLM 拒答兩條出口共用同一句，不會只有一邊講補查。"""
        no_hits, _ = build_pipeline([])
        llm_refused, _ = build_pipeline(
            [make_hit(1, "擦邊優惠", 0.30)], reply="目前資料庫沒有相關優惠資訊。"
        )
        assert no_hits.answer("火星旅遊").answer == NO_RESULT_ANSWER
        assert llm_refused.answer("火星旅遊").answer == NO_RESULT_ANSWER
