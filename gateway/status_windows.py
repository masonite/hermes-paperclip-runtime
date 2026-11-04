"""Identity-checked Windows force termination when taskkill stalls."""
import os
import signal
import subprocess

from hermes_cli._subprocess_compat import windows_hide_flags


def terminate_tree(pid: int, expected_start_time: float) -> None:
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10, creationflags=windows_hide_flags(),
        )
    except FileNotFoundError:
        os.kill(pid, signal.SIGTERM)
        return
    except subprocess.TimeoutExpired:
        _terminate_stalled_tree(pid, expected_start_time)
        return
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise OSError(details or f"taskkill failed for PID {pid}")


def _terminate_stalled_tree(pid: int, expected_start_time: float) -> None:
    import psutil
    from agent.deadline import _process_tree_snapshot

    try:
        root = psutil.Process(pid)
        if round(root.create_time() * 100) != expected_start_time:
            raise OSError(f"refusing to force-kill PID {pid}; process identity changed")
        # Retain this identity through the stop/rescan so PID reuse cannot adopt a stranger.
        with _process_tree_snapshot(pid, hard_kill=True, root=root, strict=True) as children:
            targets = [*children, root]
            for target in targets:
                try:
                    target.kill()
                except psutil.NoSuchProcess:
                    pass
            _gone, alive = psutil.wait_procs(targets, timeout=5)
            if alive:
                raise OSError(f"force-kill left processes alive: {[p.pid for p in alive]}")
    except psutil.Error as exc:
        raise OSError(f"could not terminate Windows process tree {pid}: {exc}") from exc
