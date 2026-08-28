"""環境變數管理（pydantic-settings）。密鑰只從 .env / 環境讀，一律不硬編碼。"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# LLM 逾時契約單一來源（F18）：api/main.py 直接用；bot/api_client.py 的 client 逾時
# 由此值加安全邊際導出，維持 client > server 的關係，不寫死第二個獨立數字。
QUERY_TIMEOUT_SECONDS = 90.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "ollama"
    # 127.0.0.1 而非 localhost：Windows 解析 localhost 會先試 IPv6 ::1，closed 端點
    # 要等約 2 秒才 fallback 到 IPv4，每次 LLM 呼叫都白付（同機實測 2.0s vs 0.016s，
    # 2026/08/27）。ollama 只監聽 IPv6 的環境用 .env 覆寫回 localhost 即可
    ollama_base_url: str = "http://127.0.0.1:11434"
    # 預設 qwen3:8b：generator 的 prompt 配方（think-off、指令置尾）是針對它實測調的（D6）
    ollama_model: str = "qwen3:8b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # F13 網搜補資料：缺 key 由 rag/web_search.py 的 build_search fail fast
    tavily_api_key: str = ""
    telegram_bot_token: str = ""
    # DB 路徑單一來源（F18）：env var 統一為 OFFER_RADAR_DB（原 scraper/runner.py 直讀的
    # 名稱），DATABASE_PATH 已移除，避免雙軌漂移
    database_path: str = Field(default="data/offers.db", validation_alias="OFFER_RADAR_DB")
    chroma_path: str = "data/chroma"
    api_base_url: str = "http://localhost:8000"
    # 中文檢索需要 multilingual 模型（PRD 技術約束）。選型實測（DECISIONS D6）：
    # MiniLM 與 e5-small 鑑別度不足（好市多查詢排不進 top12），bge-m3 排序正確且邊際夠；
    # 若換回 e5 系列，Embedder 會自動補 query:/passage: 前綴
    embedding_model: str = "BAAI/bge-m3"
