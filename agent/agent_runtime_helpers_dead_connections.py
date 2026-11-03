"""Pre-turn dead-connection sweep over an agent's OpenAI client pools (primary + cached request
client). Sibling of ``agent.agent_runtime_helpers``, which owns the pool-socket walk."""

from __future__ import annotations

import contextlib
import logging
import sys
import time
from typing import Any

logger = logging.getLogger("run_agent")  # origin module's logger name: log records / caplog filters unchanged


def _socket_is_dead(sock) -> bool:
    """Probe socket health with a non-blocking recv peek."""
    import socket as _socket
    timeout = sock.gettimeout()
    try:
        sock.setblocking(False)
        return _socket.socket.recv(sock, 1, _socket.MSG_PEEK) == b""
    except BlockingIOError:
        return False  # no data available: socket is healthy
    except OSError:
        return True
    finally:
        with contextlib.suppress(OSError):
            sock.settimeout(timeout)


def _prepare_interruptible_read(stream: Any) -> None:
    """Windows shutdown does not wake select; poll reads without changing the request budget."""
    if sys.platform != "win32":
        return
    from httpcore import ReadError, ReadTimeout
    from httpcore._backends.sync import SyncStream

    if not isinstance(stream, SyncStream) or getattr(stream, "_hermes_interruptible_read", False):
        return
    original = stream.read

    def read(max_bytes: int, timeout: float | None = None) -> bytes:
        if timeout is not None and timeout <= 0.25:
            return original(max_bytes, timeout=timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = 0.25 if deadline is None else max(0.0, min(0.25, deadline - time.monotonic()))
            try:
                return original(max_bytes, timeout=remaining)
            except ReadTimeout as exc:
                if _socket_is_dead(stream._sock):
                    raise ReadError("Stream socket was shut down") from exc
                if deadline is not None and time.monotonic() >= deadline:
                    raise

    stream.read = read
    stream._hermes_interruptible_read = True


def _socket_from_stream(stream: Any):
    """Raw socket behind an httpcore network stream (several backends), or None."""
    _prepare_interruptible_read(stream)
    sock = getattr(stream, "_sock", None)
    if sock is None and callable(getattr(stream, "get_extra_info", None)):
        with contextlib.suppress(Exception):
            sock = stream.get_extra_info("socket")
    if sock is None:
        sock = getattr(getattr(stream, "stream", None), "_sock", None)
    if sock is None and callable(getattr(getattr(stream, "_stream", None), "extra", None)):
        # anyio-backed streams expose the raw socket through SocketAttribute.raw_socket.
        with contextlib.suppress(Exception):
            from anyio.abc import SocketAttribute
            sock = stream._stream.extra(SocketAttribute.raw_socket)
    return sock


def _count_dead_pool_sockets(client: Any) -> int:
    """Return the number of sockets in ``client``'s pool that have reached EOF (CLOSE-WAIT)."""
    from agent.agent_runtime_helpers import _iter_pool_sockets
    return sum(1 for sock in _iter_pool_sockets(client) if _socket_is_dead(sock))


def cleanup_dead_connections(agent) -> bool:
    """Detect and clean up dead TCP connections owned by an agent.

    Long-lived chat-completion turns use a cached per-request OpenAI client
    for sequential calls, while ``agent.client`` remains the primary client
    used for runtime rebuilds and provider management.  Inspect both pools:
    a provider FIN on the cached client otherwise stays in CLOSE-WAIT until
    session teardown and can be handed back to the next request.

    Dead sockets on the primary client rebuild that client.  Dead sockets on
    the request cache go through the cache's ownership-aware teardown hook so
    an in-flight worker is aborted safely and an idle client is closed by its
    owner.  Returns True if dead connections were found and cleaned up.
    """
    primary = getattr(agent, "client", None)
    cache = getattr(agent, "_request_client_cache", None)
    request_client = cache.get("client") if isinstance(cache, dict) else None

    clients: list[tuple[str, Any]] = []
    if primary is not None:
        clients.append(("primary", primary))
    if request_client is not None and request_client is not primary:
        clients.append(("request", request_client))
    if not clients:
        return False

    dead_clients: list[tuple[str, Any, int]] = []
    for label, client in clients:
        try:
            dead_count = _count_dead_pool_sockets(client)
            if dead_count:
                dead_clients.append((label, client, dead_count))
        except Exception:
            # Best-effort probe over private httpcore internals: one client's failure must not
            # skip the other's check or abort the turn.
            logger.debug("Dead connection check error for %s client", label, exc_info=True)

    if not dead_clients:
        return False

    total_dead = sum(count for _label, _client, count in dead_clients)
    labels = ", ".join(label for label, _client, _count in dead_clients)
    logger.warning(
        "Found %d dead connection(s) in %s client pool(s) — cleaning up",
        total_dead,
        labels,
    )

    for label, _client, _count in dead_clients:
        try:
            if label == "primary":
                agent._replace_primary_openai_client(reason="dead_connection_cleanup")
            else:
                # This hook clears the cache and chooses close() vs socket
                # shutdown based on whether another worker owns the client.
                agent._close_cached_request_openai_client(reason="dead_connection_cleanup")
        except Exception:
            # Cleaning one pool must not stop the other pool's cleanup.
            logger.debug("Dead connection cleanup error for %s client", label, exc_info=True)
    return True
