"""環境變數管理（pydantic-settings）。密鑰只從 .env / 環境讀，一律不硬編碼。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    telegram_bot_token: str = ""
    database_path: str = "data/offers.db"
    chroma_path: str = "data/chroma"
    api_base_url: str = "http://localhost:8000"
    # 中文檢索需要 multilingual 模型（PRD 技術約束）
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
