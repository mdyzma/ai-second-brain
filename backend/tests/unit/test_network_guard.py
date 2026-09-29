import socket

import pytest
from pytest_socket import SocketConnectBlockedError


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_network_guard_blocks_non_loopback_hosts() -> None:
    # 192.0.2.0/24 is TEST-NET-1: never routable. The guard must refuse before any packet.
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.2)
