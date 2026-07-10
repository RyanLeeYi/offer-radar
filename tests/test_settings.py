"""config.settings 測試：預設值 + 環境變數覆寫（密鑰只從環境讀，不硬編碼）。"""

from config.settings import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert settings.database_path == "data/offers.db"
    assert settings.chroma_path == "data/chroma"
    assert "multilingual" in settings.embedding_model.lower()


def test_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "elsewhere/offers.db")
    monkeypatch.setenv("EMBEDDING_MODEL", "some/other-multilingual-model")
    settings = Settings(_env_file=None)
    assert settings.database_path == "elsewhere/offers.db"
    assert settings.embedding_model == "some/other-multilingual-model"
