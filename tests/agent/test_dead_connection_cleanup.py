"""Regression tests for stale provider sockets in agent-owned client pools."""

import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.agent_runtime_helpers_dead_connections import _socket_from_stream, cleanup_dead_connections


@pytest.fixture
def clients():
    healthy, healthy_peer = socket.socketpair()
    dead, dead_peer = socket.socketpair()
    with healthy, healthy_peer, dead, dead_peer:
        healthy.settimeout(2)
        dead.settimeout(3)
        dead_peer.shutdown(socket.SHUT_WR)
        yield _client_with_socket(healthy), _client_with_socket(dead)
        assert healthy.gettimeout() == 2
        assert dead.gettimeout() == 3


def _client_with_socket(sock):
    stream = SimpleNamespace(_sock=sock)
    http11 = SimpleNamespace(_network_stream=stream)
    pool_entry = SimpleNamespace(_connection=http11)
    pool = SimpleNamespace(_connections=[pool_entry])
    transport = SimpleNamespace(_pool=pool)
    http_client = SimpleNamespace(_transport=transport)
    return SimpleNamespace(_client=http_client)


def test_cleanup_retires_dead_cached_request_client(clients):
    """A half-closed request pool must not be hidden by a healthy primary."""
    primary, request = clients
    agent = SimpleNamespace(
        client=primary,
        _request_client_cache={"client": request},
        _replace_primary_openai_client=MagicMock(),
        _close_cached_request_openai_client=MagicMock(),
    )

    assert cleanup_dead_connections(agent) is True
    agent._replace_primary_openai_client.assert_not_called()
    agent._close_cached_request_openai_client.assert_called_once_with(
        reason="dead_connection_cleanup"
    )


def test_cleanup_rebuilds_dead_primary_client(clients):
    """The existing primary-client recovery remains the cleanup path."""
    request, primary = clients
    agent = SimpleNamespace(
        client=primary,
        _request_client_cache={"client": request},
        _replace_primary_openai_client=MagicMock(),
        _close_cached_request_openai_client=MagicMock(),
    )

    assert cleanup_dead_connections(agent) is True
    agent._replace_primary_openai_client.assert_called_once_with(
        reason="dead_connection_cleanup"
    )
    agent._close_cached_request_openai_client.assert_not_called()


@pytest.mark.platforms("windows")
@pytest.mark.parametrize("deliver", [False, True], ids=["request-timeout", "delayed-data"])
def test_stream_read_preserves_request_budget(deliver):
    from httpcore import ReadTimeout
    from httpcore._backends.sync import SyncStream

    reader, writer = socket.socketpair()
    with reader, writer:
        stream = SyncStream(reader)
        assert _socket_from_stream(stream) is reader
        timer = threading.Timer(0.75, writer.sendall, args=(b"ready",)) if deliver else None
        if timer is not None:
            timer.start()
        try:
            started = time.monotonic()
            if deliver:
                assert stream.read(5, timeout=3) == b"ready"
            else:
                with pytest.raises(ReadTimeout):
                    stream.read(5, timeout=2)
                assert 1.8 <= time.monotonic() - started < 5
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
