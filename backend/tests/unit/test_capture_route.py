from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from ai_second_brain.interfaces.api.routes.capture import capture_note
from ai_second_brain.interfaces.api.schemas import CaptureRequest

from ..conftest import run_async


def test_lone_surrogate_is_invalid_text_and_writes_nothing(tmp_path: Path) -> None:
    # Pydantic rejects this today; the route still refuses it if a body ever gets through.
    settings = SimpleNamespace(vault_path=tmp_path, capture_dir=tmp_path / "Inbox")
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    body = CaptureRequest.model_construct(text="note \ud800 text")
    with pytest.raises(HTTPException) as error:
        run_async(capture_note(body, request))
    assert error.value.status_code == 422 and error.value.detail == "invalid_text"
    assert not (tmp_path / "Inbox").exists()
