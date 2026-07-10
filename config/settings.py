"""環境變數管理（pydantic-settings）。密鑰只從 .env / 環境讀，一律不硬編碼。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    # 預設 qwen3:8b：generator 的 prompt 配方（think-off、指令置尾）是針對它實測調的（D6）
    ollama_model: str = "qwen3:8b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    telegram_bot_token: str = ""
    database_path: str = "data/offers.db"
    chroma_path: str = "data/chroma"
    api_base_url: str = "http://localhost:8000"
    # 中文檢索需要 multilingual 模型（PRD 技術約束）。選型實測（DECISIONS D6）：
    # MiniLM 與 e5-small 鑑別度不足（好市多查詢排不進 top12），bge-m3 排序正確且邊際夠；
    # 若換回 e5 系列，Embedder 會自動補 query:/passage: 前綴
    embedding_model: str = "BAAI/bge-m3"
