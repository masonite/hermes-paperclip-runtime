"""A stalled taskkill never strands the owned tree or kills a reused PID."""
import json
import subprocess
import sys
import time

import psutil
import pytest

from gateway import status, status_windows

pytestmark = pytest.mark.platforms("windows")


@pytest.fixture
def process_tree(tmp_path):
    info = tmp_path / "child.json"
    sleeper = [sys._base_executable, "-c", "import time; time.sleep(120)"]
    script = (f"import sys; sys.path[:] = {sys.path!r}\n"
              "import json, subprocess, time, psutil\nfrom pathlib import Path\n"
              f"child = subprocess.Popen({sleeper!r})\n"
              f"Path({str(info)!r}).write_text(json.dumps([child.pid, psutil.Process(child.pid).create_time()]))\n"
              "time.sleep(120)\n")
    root = subprocess.Popen([sys._base_executable, "-c", script], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    stranger = subprocess.Popen(sleeper, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while not info.exists():
            assert root.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        child_pid, created = json.loads(info.read_text())
        yield root, child_pid, stranger
    finally:
        for proc in (root, stranger):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        if info.exists():
            try:
                child_pid, created = json.loads(info.read_text())
                child = psutil.Process(child_pid)
                if child.create_time() == created:
                    child.kill()
                    child.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass


def test_taskkill_timeout_reaps_owned_tree_and_spares_sibling(process_tree, monkeypatch):
    root, child_pid, stranger = process_tree

    def stalled(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(status_windows.subprocess, "run", stalled)
    status.terminate_pid(root.pid, force=True, expected_start_time=status.get_process_start_time(root.pid))
    root.wait(timeout=10)
    assert not psutil.pid_exists(child_pid)
    assert stranger.poll() is None


def test_timeout_fallback_rechecks_original_birth(process_tree):
    root, child_pid, stranger = process_tree
    with pytest.raises(OSError, match="identity changed"):
        status_windows._terminate_stalled_tree(root.pid, status.get_process_start_time(root.pid) + 10000)
    assert root.poll() is None and psutil.pid_exists(child_pid)
    assert stranger.poll() is None


def test_incomplete_tree_snapshot_refuses_fallback_kill(process_tree, monkeypatch):
    root, child_pid, stranger = process_tree

    def denied(self, **kwargs):
        raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(psutil.Process, "children", denied)
    with pytest.raises(OSError, match="could not terminate"):
        status_windows._terminate_stalled_tree(root.pid, status.get_process_start_time(root.pid))
    assert root.poll() is None and psutil.pid_exists(child_pid)
    assert stranger.poll() is None
