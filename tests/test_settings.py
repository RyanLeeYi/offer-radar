"""config.settings 測試：預設值 + 環境變數覆寫（密鑰只從環境讀，不硬編碼）。"""

import importlib

from config.settings import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert settings.database_path == "data/offers.db"
    assert settings.chroma_path == "data/chroma"
    assert settings.embedding_model == "BAAI/bge-m3"  # 中文檢索選型見 DECISIONS D6
    # F26：127.0.0.1 而非 localhost。Windows 解析 localhost 先試 IPv6 ::1，每次多付約
    # 2 秒才 fallback 到 IPv4（實測 2.0s vs 0.016s），而每次 LLM 呼叫都走這個位址
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    # F27：bot 呼叫 /query 走的是同一條路，付同一份 IPv6 fallback 成本
    assert settings.api_base_url == "http://127.0.0.1:8000"


def test_ollama_base_url_env_override(monkeypatch):
    """F26 只換預設值，不封死 localhost——ollama 只監聽 IPv6 的環境要覆寫得回去。"""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert Settings(_env_file=None).ollama_base_url == "http://localhost:11434"


def test_api_base_url_env_override(monkeypatch):
    """F27 同樣只換預設值：API 綁在別的位址（容器、遠端主機）時要覆寫得回去。"""
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8000")
    assert Settings(_env_file=None).api_base_url == "http://localhost:8000"


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
