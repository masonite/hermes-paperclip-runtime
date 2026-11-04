"""Inject Git faults at both native subprocess and Windows update-custody boundaries."""
import subprocess

from hermes_cli import update_custody


def patch_update_run(monkeypatch, fault):
    subprocess_run, custody_run = subprocess.run, update_custody.run
    active = False

    def intercept(run, command, *args, **kwargs):
        nonlocal active
        if active:
            return run(command, *args, **kwargs)
        active = True
        try:
            return fault(run, command, *args, **kwargs)
        finally:
            active = False

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: intercept(subprocess_run, *a, **k))
    monkeypatch.setattr(update_custody, "run", lambda *a, **k: intercept(custody_run, *a, **k))
