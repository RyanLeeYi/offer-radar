"""Embedder 測試：e5 系列模型要加 query:/passage: 前綴，其他模型不加。

模型載入用注入的 fake loader，不下載真模型。
"""

from rag.embedder import Embedder


class FakeModel:
    def __init__(self):
        self.seen: list[list[str]] = []

    def encode(self, texts, show_progress_bar=False):
        self.seen.append(list(texts))

        class _Arr:
            def __init__(self, n):
                self._n = n

            def tolist(self):
                return [[0.1, 0.2]] * self._n

        return _Arr(len(texts))


def make_embedder(model_name: str) -> tuple[Embedder, FakeModel]:
    fake = FakeModel()
    return Embedder(model_name, load=lambda name: fake), fake


class TestE5Prefixes:
    def test_passages_get_passage_prefix(self):
        embedder, fake = make_embedder("intfloat/multilingual-e5-small")
        embedder.embed_passages(["優惠內容甲", "優惠內容乙"])
        assert fake.seen[0] == ["passage: 優惠內容甲", "passage: 優惠內容乙"]

    def test_query_gets_query_prefix(self):
        embedder, fake = make_embedder("intfloat/multilingual-e5-small")
        embedder.embed_query("去好市多刷哪張卡")
        assert fake.seen[0] == ["query: 去好市多刷哪張卡"]


class TestNonE5NoPrefix:
    def test_passages_unprefixed(self):
        embedder, fake = make_embedder("paraphrase-multilingual-MiniLM-L12-v2")
        embedder.embed_passages(["優惠內容"])
        assert fake.seen[0] == ["優惠內容"]

    def test_query_unprefixed(self):
        embedder, fake = make_embedder("paraphrase-multilingual-MiniLM-L12-v2")
        embedder.embed_query("問題")
        assert fake.seen[0] == ["問題"]


def test_model_loaded_lazily_and_once():
    loads: list[str] = []
    fake = FakeModel()

    def load(name: str):
        loads.append(name)
        return fake

    embedder = Embedder("intfloat/multilingual-e5-small", load=load)
    assert loads == []  # 建構時不載入
    embedder.embed_query("q")
    embedder.embed_passages(["p"])
    assert loads == ["intfloat/multilingual-e5-small"]  # 只載一次
