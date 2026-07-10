"""Embedding：sentence-transformers 薄封裝，模型名由 config 決定（須支援中文）。"""

from sentence_transformers import SentenceTransformer


class Embedder:
    """延遲載入模型（首次呼叫才下載/載入，測試與 CLI --help 不用等）。"""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model.encode(texts, show_progress_bar=False).tolist()
