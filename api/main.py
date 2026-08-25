"""FastAPI /query + /health（PRD R4+R5）：薄封裝，只呼叫 rag/pipeline.py。

啟動：``uv run uvicorn api.main:app``。重物件（torch/embedding 模型）在 lifespan
才組裝，import 本模組不觸發；測試經 create_app 注入 RagRuntime（fake），
完全不碰網路與模型。LLM 逾時契約常數在 config/settings.py（QUERY_TIMEOUT_SECONDS，
90 秒；涵蓋 8B 冷載入實測 ~24s 的最壞情況，30 秒會誤砍；generator transport 層
120 秒仍為最外層上界），bot/api_client.py 的 client 逾時由此值加安全邊際導出。
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.schemas import ErrorResponse, HealthResponse, QueryRequest, QueryResponse, SourceOut
from config.settings import QUERY_TIMEOUT_SECONDS
from rag.pipeline import RagRuntime, build_default

KB_NOT_READY_ERROR = "知識庫尚未建立"
LLM_TIMEOUT_ERROR = "LLM 回應逾時，請稍後再試"


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content=ErrorResponse(error=message).model_dump()
    )


def create_app(
    runtime: RagRuntime | None = None,
    query_timeout: float = QUERY_TIMEOUT_SECONDS,
) -> FastAPI:
    """未注入 runtime 時（正式環境）於 lifespan 依 Settings 組裝。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.runtime is None:
            from config.settings import Settings

            app.state.runtime = build_default(Settings())
        yield

    app = FastAPI(title="offer-radar", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.query_timeout = query_timeout

    @app.post(
        "/query",
        response_model=QueryResponse,
        responses={503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
    )
    async def query(request: QueryRequest):
        rag: RagRuntime = app.state.runtime
        # stats/pipeline 都是阻塞呼叫（ChromaDB/embedding/LLM），一律下放 thread，
        # 不佔 event loop
        if await asyncio.to_thread(rag.stats.count) == 0:
            return _error(503, KB_NOT_READY_ERROR)
        try:
            # 逾時後 thread 仍會跑完（Python 無法安全砍 thread），只是回應不等它
            result = await asyncio.wait_for(
                asyncio.to_thread(rag.pipeline.answer, request.question),
                timeout=app.state.query_timeout,
            )
        except TimeoutError:
            return _error(504, LLM_TIMEOUT_ERROR)
        return QueryResponse(
            answer=result.answer,
            sources=[SourceOut.model_validate(s) for s in result.sources],
        )

    @app.get("/health", response_model=HealthResponse)
    async def health():
        rag: RagRuntime = app.state.runtime
        offers = await asyncio.to_thread(rag.stats.offers_count)
        last_ingest = await asyncio.to_thread(rag.stats.last_ingest_at)
        return HealthResponse(status="ok", offers_count=offers, last_ingest_at=last_ingest)

    return app


app = create_app()
