"""混合檢索測試（F4）：關鍵詞精確匹配 + 向量檢索合併。

背景：商家名（好市多、蝦皮）在長條款 chunk 裡會被向量稀釋，
純向量檢索排不進 top-k——關鍵詞 $contains 直達，向量負責其餘語意。
"""

from rag.keywords import candidate_terms
from rag.retriever import Retriever
from rag.vector_store import Hit, VectorStore


class TestCandidateTerms:
    def test_extracts_merchant_ngrams(self):
        terms = candidate_terms("去好市多刷哪張卡最划算")
        assert "好市多" in terms

    def test_short_merchant_included(self):
        assert "全家" in candidate_terms("全家有什麼優惠")

    def test_pure_stopchar_grams_excluded(self):
        terms = candidate_terms("去好市多刷哪張卡最划算")
        assert "哪張" not in terms
        assert "划算" not in terms

    def test_no_duplicates(self):
        terms = candidate_terms("好市多好市多")
        assert len(terms) == len(set(terms))

    def test_latin_merchant_names_kept_whole(self):
        terms = candidate_terms("momo有什麼優惠")
        assert "momo" in terms
        terms = candidate_terms("Uber Eats 訂餐優惠")
        assert "Uber" in terms and "Eats" in terms


class TestVectorStoreContaining(object):
    def test_query_containing_filters_by_substring(self, tmp_path):
        store = VectorStore(path=str(tmp_path / "chroma"))
        store.upsert(
            ids=["1:0", "2:0"],
            texts=["優食好市多專區享2%回饋", "看電影平日6折"],
            embeddings=[[0.0, 1.0], [1.0, 0.0]],
            metadatas=[
                {"offer_id": 1, "valid_to": "", "source_url": "https://a", "title": "好市多"},
                {"offer_id": 2, "valid_to": "", "source_url": "https://b", "title": "電影"},
            ],
        )
        # embedding 故意偏向「電影」，$contains 仍只回好市多那筆
        hits = store.query_containing("好市多", embedding=[1.0, 0.0], top_k=5)
        assert [h.metadata["offer_id"] for h in hits] == [1]

    def test_query_containing_no_match_returns_empty(self, tmp_path):
        store = VectorStore(path=str(tmp_path / "chroma"))
        store.upsert(
            ids=["1:0"],
            texts=["看電影平日6折"],
            embeddings=[[1.0, 0.0]],
            metadatas=[{"offer_id": 1, "valid_to": "", "source_url": "https://a", "title": "t"}],
        )
        assert store.query_containing("好市多", embedding=[1.0, 0.0], top_k=5) == []


class FakeStore:
    """關鍵詞命中「沉底正解」、向量檢索回一堆語意近似的雜訊。"""

    def __init__(self):
        self.noise = [
            Hit(text=f"雜訊{i}", metadata={"offer_id": i, "title": f"雜訊{i}"}, distance=0.30 + i * 0.01)
            for i in range(10)
        ]
        self.costco = Hit(
            text="優食好市多專區享2%回饋",
            metadata={"offer_id": 99, "title": "優食好市多專區享2%回饋"},
            distance=0.45,
        )

    def query(self, embedding, top_k):
        return self.noise[:top_k]

    def query_containing(self, term, embedding, top_k):
        return [self.costco] if term in self.costco.text else []


class TestHybridRetriever:
    def test_keyword_hits_rank_ahead_of_vector_hits(self):
        retriever = Retriever(store=FakeStore(), embed_query=lambda q: [0.1, 0.2])
        hits = retriever.retrieve("去好市多刷哪張卡最划算")
        assert hits[0].metadata["offer_id"] == 99  # 關鍵詞直達的正解排最前
        assert len(hits) > 1  # 向量結果仍在後面

    def test_no_keyword_match_falls_back_to_vector_only(self):
        retriever = Retriever(store=FakeStore(), embed_query=lambda q: [0.1, 0.2])
        hits = retriever.retrieve("火星旅遊")
        assert all(h.metadata["offer_id"] != 99 for h in hits)

    def test_merged_hits_deduped(self):
        store = FakeStore()
        store.noise.insert(0, store.costco)  # 正解同時出現在向量結果
        retriever = Retriever(store=store, embed_query=lambda q: [0.1, 0.2])
        hits = retriever.retrieve("好市多優惠")
        ids = [(h.metadata["offer_id"], h.text) for h in hits]
        assert len(ids) == len(set(ids))
