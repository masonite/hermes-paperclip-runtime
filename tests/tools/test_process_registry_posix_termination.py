import pytest


@pytest.mark.platforms("posix")
def test_posix_terminates_parent_before_snapshot_descendants(self, monkeypatch):
    from tools import process_registry as pr
    import psutil

    terminate_order = []

    class _FakeChild:
        def __init__(self, pid):
            self.pid = pid

        def terminate(self):
            terminate_order.append(self.pid)

    class _FakeParent:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=False):
            assert recursive is True
            return [_FakeChild(101), _FakeChild(102), _FakeChild(103)]

        def terminate(self):
            terminate_order.append(self.pid)

    monkeypatch.setattr(psutil, "Process", _FakeParent)
    # A zero grace keeps this ordering probe deterministic while retaining
    # the configured no-SIGKILL behavior.
    monkeypatch.setattr(pr.ProcessRegistry, "_daemon_term_grace_seconds",
                        staticmethod(lambda: 0.0))

    pr.ProcessRegistry._terminate_host_pid(12345)

    assert terminate_order == [12345, 101, 102, 103], (
        "Parent must receive SIGTERM before any snapshot descendant"
    )
