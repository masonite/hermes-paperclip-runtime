"""Finished sessions never close a pipe underneath its active reader."""
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from tools.process_registry import ProcessRegistry, ProcessSession


def test_pipe_close_is_deferred_to_the_reader():
    stream = MagicMock()
    session = ProcessSession(id="pipe-close", command="test")
    session.process = SimpleNamespace(stdout=stream, stderr=None, stdin=None)
    session._reader_thread = SimpleNamespace(is_alive=lambda: True)
    registry = ProcessRegistry()
    registry._release_finished_handles(session)
    stream.close.assert_not_called()
    session._reader_thread = None
    registry._release_finished_handles(session)
    stream.close.assert_called_once()


def test_exited_parent_with_a_live_pipe_writer_finishes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    writer = subprocess.Popen([sys._base_executable, "-c", "import time; time.sleep(30)"],
                              stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    session = ProcessSession(id="orphaned-pipe", command="test")
    session.process = SimpleNamespace(stdout=writer.stdout, stderr=None, stdin=None,
                                      pid=writer.pid, poll=lambda: 0, wait=lambda: 0, returncode=0)
    registry = ProcessRegistry()
    try:
        registry._track_started(session, registry._reader_loop, "pipe-cleanup-test")
        session._reader_thread.join(timeout=5)
        assert not session._reader_thread.is_alive()
        assert session._completion_event.is_set()
        assert writer.stdout.closed
        assert writer.poll() is None
    finally:
        writer.kill()
        writer.wait(timeout=10)
