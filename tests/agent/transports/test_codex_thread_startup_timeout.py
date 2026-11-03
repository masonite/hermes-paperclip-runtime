"""Thread setup must tolerate Codex plugin initialization during concurrent launches."""

import threading
from unittest.mock import Mock

import pytest

from agent.transports.codex_app_server import CodexAppServerClient
from agent.transports.codex_app_server_session import CodexAppServerSession


@pytest.mark.parametrize("resume_thread_id", [None, "thread-slow-startup"])
def test_thread_setup_waits_for_slow_server_reply(resume_thread_id):
    client = object.__new__(CodexAppServerClient)
    client._closed = False
    client._pending = {}
    client._pending_lock = threading.Lock()
    client._next_id = 1
    client.initialize = Mock(return_value={})
    client.close = Mock()
    replies = []

    def send(message):
        pending = client._pending[message["id"]]
        # Plugin startup can outlast the former 15-second thread setup deadline.
        reply = threading.Timer(17, pending.put, args=({"result": {"thread": {"id": "thread-slow-startup"}}},))
        reply.daemon = True
        replies.append(reply)
        reply.start()

    client._send = send
    session = CodexAppServerSession(client_factory=lambda **kwargs: client, resume_thread_id=resume_thread_id)
    try:
        assert session.ensure_started() == "thread-slow-startup"
        assert session.ensure_started() == "thread-slow-startup"
        assert len(replies) == 1
    finally:
        session.close()
        for reply in replies:
            reply.join(timeout=30)
