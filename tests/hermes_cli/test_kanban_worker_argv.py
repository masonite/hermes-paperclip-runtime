import os


def test_resolve_hermes_argv_prefers_module_form_over_path_shim(monkeypatch):
    """A `hermes` on PATH must not shadow the running install (#111569):
    the module argv wins whenever ``hermes_cli`` is importable; only an
    explicit ``$HERMES_BIN`` overrides it."""
    import shutil
    import sys
    from hermes_cli import kanban_db_dispatch as kbd

    monkeypatch.delenv("HERMES_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/tmp/planted/hermes")
    monkeypatch.setattr(kbd, "_safe_which_no_cwd", lambda name: "/tmp/planted/hermes")
    assert kbd._resolve_hermes_argv() == [sys.executable, "-m", "hermes_cli.main"]

    monkeypatch.setenv("HERMES_BIN", "/opt/hermes/bin/hermes")
    assert kbd._resolve_hermes_argv() == [os.path.abspath("/opt/hermes/bin/hermes")]
