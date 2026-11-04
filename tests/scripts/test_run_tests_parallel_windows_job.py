"""The Windows runner reaps pipe-holding grandchildren when pytest itself exits."""
import json
import os
import subprocess
import sys
import time

import psutil
import pytest

from tests.scripts.test_run_tests_parallel import _probe_root


@pytest.mark.platforms("windows")
@pytest.mark.live_system_guard_bypass
def test_exited_worker_reaps_grandchild_holding_stdout(tmp_path):
    root = _probe_root(tmp_path)
    marker = "hermes-runner-job-pipe-writer"
    pid_file = root / "writer.json"
    probe = root / "test_pipe_writer.py"
    probe.write_text(
        "import json, subprocess, psutil\nfrom pathlib import Path\n"
        "def test_writer():\n"
        f"    child = subprocess.Popen([{sys._base_executable!r}, '-c', "
        f"'import time; time.sleep(120) # {marker}'])\n"
        f"    Path({str(pid_file)!r}).write_text(json.dumps([child.pid, psutil.Process(child.pid).create_time()]))\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, str(root / "scripts/run_tests_parallel.py"), str(probe),
             "-j", "1", "--file-timeout", "10", "--file-retries", "0", "-s", "-q"],
            cwd=root, env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        pid, _created = json.loads(pid_file.read_text())
        deadline = time.monotonic() + 5
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(pid), "the writer outlived its finished pytest worker"
    finally:
        if pid_file.exists():
            try:
                pid, created = json.loads(pid_file.read_text())
                child = psutil.Process(pid)
                if child.create_time() == created:
                    child.kill()
                    child.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
