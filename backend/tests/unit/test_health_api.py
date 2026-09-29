from collections.abc import Callable

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app, openapi_schema

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
    assert response.json() == {"detail": "Not Found"}


def test_openapi_schema_has_stable_operation_ids() -> None:
    schema = openapi_schema()
    operation_ids = {
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    }
    assert {"health", "ready"} <= operation_ids
