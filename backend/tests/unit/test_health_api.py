import logging
from collections.abc import Callable

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app, openapi_schema
from ai_second_brain.runtime import new_event_loop

from ..conftest import make_client


def test_health_is_ok_without_database(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_is_503_when_database_unreachable(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "error"}


def test_docs_enabled_in_dev_only(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings(env="dev"))) as client:
        assert client.get("/api/docs").status_code == 200
    with make_client(create_app(make_settings(env="prod"))) as client:
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404


def test_unknown_route_is_404_detail_shape(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}


def test_openapi_schema_has_stable_operation_ids() -> None:
    schema = openapi_schema()
    operation_ids = {
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    }
    assert {"health", "ready", "login", "logout", "me"} <= operation_ids


def test_method_not_allowed_is_snake_case(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.post("/api/health")
    assert response.status_code == 405
    assert response.json() == {"detail": "method_not_allowed"}


def test_explicit_http_exception_detail_and_headers_pass_through(
    make_settings: Callable[..., Settings],
) -> None:
    app = create_app(make_settings())

    @app.get("/api/boom")
    async def boom() -> None:
        raise HTTPException(429, detail="too_many_attempts", headers={"Retry-After": "7"})

    with make_client(app) as client:
        response = client.get("/api/boom")
    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_attempts"}
    assert response.headers["Retry-After"] == "7"


def test_unhandled_error_is_still_logged_with_status_500(
    make_settings: Callable[..., Settings], caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(make_settings())

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("secret-detail")

    caplog.set_level(logging.INFO, logger="ai_second_brain.api")
    with TestClient(
        app, raise_server_exceptions=False, backend_options={"loop_factory": new_event_loop}
    ) as client:
        response = client.get("/api/boom")
    assert response.status_code == 500
    assert "GET /api/boom 500" in caplog.text
    assert "secret-detail" not in caplog.text
