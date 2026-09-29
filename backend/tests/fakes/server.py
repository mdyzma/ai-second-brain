"""Serve an ASGI app on 127.0.0.1:<random port> in a background thread."""

import socket
import threading
import time

import uvicorn
from starlette.types import ASGIApp


class ServerThread:
    def __init__(self, app: ASGIApp) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            lifespan="off",
            timeout_graceful_shutdown=1,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._sock]}, daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 5
        while not self._server.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("fake server did not start")
            time.sleep(0.01)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self._sock.close()


def closed_port_url() -> str:
    """A loopback URL nothing listens on (connection refused immediately)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"
