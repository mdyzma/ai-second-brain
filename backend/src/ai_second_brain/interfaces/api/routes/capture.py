import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import CaptureRequest, CaptureResponse, ErrorResponse
from ai_second_brain.search.links import obsidian_url
from ai_second_brain.vault import capture as capture_module

logger = logging.getLogger("ai_second_brain.capture")
router = APIRouter(tags=["capture"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {
    k: {"model": ErrorResponse} for k in (401, 403, 409, 422, 503)
}


@router.post(
    "/capture",
    operation_id="captureNote",
    status_code=status.HTTP_201_CREATED,
    response_model=CaptureResponse,
    responses=ERRORS,
    dependencies=[Depends(require_same_origin)],
)
async def capture_note(body: CaptureRequest, request: Request) -> CaptureResponse:
    settings = get_settings(request)
    if settings.vault_path is None or settings.capture_dir is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="vault_disabled")
    if not body.text.strip() or "\x00" in body.text:
        raise HTTPException(422, detail="invalid_text")
    try:
        rel = await asyncio.to_thread(
            capture_module.write_capture,
            settings.vault_path,
            settings.capture_dir,
            body.text,
            datetime.now().astimezone(),
        )
    except capture_module.CaptureNameTaken:
        logger.info("capture outcome=capture_name_taken bytes=%d", len(body.text.encode()))
        raise HTTPException(status.HTTP_409_CONFLICT, detail="capture_name_taken") from None
    except OSError as error:
        logger.warning("capture outcome=vault_unwritable type=%s", type(error).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="vault_unwritable"
        ) from None
    logger.info("capture outcome=ok bytes=%d", len(body.text.encode()))
    return CaptureResponse(
        path=rel,
        title=capture_module.capture_title(body.text),
        obsidian_url=obsidian_url(settings.obsidian_vault_name, rel),
    )
