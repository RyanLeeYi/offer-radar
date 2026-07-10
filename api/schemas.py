"""API 介面契約（Pydantic）：request 驗證在邊界擋（PRD：question 1–500 字 → 422）。"""

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SourceOut(BaseModel):
    # from_attributes：直接吃 rag/pipeline.py 的 Source dataclass，不手抄欄位
    model_config = ConfigDict(from_attributes=True)

    title: str
    source_url: str
    valid_to: str | None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceOut]


class HealthResponse(BaseModel):
    status: str
    offers_count: int
    last_ingest_at: str | None


class ErrorResponse(BaseModel):
    """503（未建庫）/ 504（LLM 逾時）的統一錯誤形狀（PRD 邊界情況）。"""

    error: str
