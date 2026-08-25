"""config.settings 測試：預設值 + 環境變數覆寫（密鑰只從環境讀，不硬編碼）。"""

import importlib

from config.settings import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert settings.database_path == "data/offers.db"
    assert settings.chroma_path == "data/chroma"
    assert settings.embedding_model == "BAAI/bge-m3"  # 中文檢索選型見 DECISIONS D6


def test_env_override(monkeypatch):
    # F18：DB 路徑單一環境變數名 OFFER_RADAR_DB（DATABASE_PATH 已移除，不再雙軌）
    monkeypatch.setenv("OFFER_RADAR_DB", "elsewhere/offers.db")
    monkeypatch.setenv("EMBEDDING_MODEL", "some/other-multilingual-model")
    settings = Settings(_env_file=None)
    assert settings.database_path == "elsewhere/offers.db"
    assert settings.embedding_model == "some/other-multilingual-model"


def test_query_timeout_single_contract_constant(monkeypatch):
    """F18：改 config.settings.QUERY_TIMEOUT_SECONDS 一處，api 與 bot 兩端數值同步變動；
    bot client 逾時維持比 server 長（安全邊際導出，非第二個獨立寫死的數字）。"""
    monkeypatch.setattr("config.settings.QUERY_TIMEOUT_SECONDS", 42.0)

    import api.main
    import bot.api_client

    importlib.reload(api.main)
    importlib.reload(bot.api_client)
    try:
        assert api.main.QUERY_TIMEOUT_SECONDS == 42.0
        assert bot.api_client._QUERY_TIMEOUT == 42.0 + bot.api_client._TIMEOUT_MARGIN_SECONDS
        assert bot.api_client._QUERY_TIMEOUT > api.main.QUERY_TIMEOUT_SECONDS
    finally:
        importlib.reload(api.main)
        importlib.reload(bot.api_client)
