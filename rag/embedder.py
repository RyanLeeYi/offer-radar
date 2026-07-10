"""Embedding：sentence-transformers 薄封裝，模型名由 config 決定（須支援中文）。

e5 系列（multilingual-e5-*）是非對稱檢索模型：文件端要加 ``passage: ``、
查詢端要加 ``query: `` 前綴，漏加會明顯掉檢索品質；其他模型不加。
"""

from collections.abc import Callable


def _load_sentence_transformer(model_name: str):
    from sentence_transformers import SentenceTransformer  # 延後 import：載 torch 很慢

    return SentenceTransformer(model_name)


class Embedder:
    """延遲載入模型（首次呼叫才下載/載入）。load 可注入供測試。"""

    def __init__(self, model_name: str, load: Callable = _load_sentence_transformer) -> None:
        self._model_name = model_name
        self._load = load
        self._model = None
        self._is_e5 = "e5" in model_name.lower()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """入庫端：文件塊 → 向量。"""
        if self._is_e5:
            texts = [f"passage: {t}" for t in texts]
        return self._encode(texts)

    def embed_query(self, question: str) -> list[float]:
        """查詢端：問題 → 向量。"""
        text = f"query: {question}" if self._is_e5 else question
        return self._encode([text])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model = self._load(self._model_name)
        return self._model.encode(texts, show_progress_bar=False).tolist()
