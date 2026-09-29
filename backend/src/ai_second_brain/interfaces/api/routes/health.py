from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ai_second_brain.db import ping
from ai_second_brain.interfaces.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", operation_id="health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    operation_id="ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
async def ready(request: Request):  # returns ReadyResponse or a 503 JSONResponse
    if await ping(request.app.state.pool):
        return ReadyResponse(status="ready", database="ok")
    return JSONResponse(status_code=503, content={"status": "unavailable", "database": "error"})
