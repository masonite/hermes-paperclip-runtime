"""Junction checks must work before a plugin's destination exists."""

from pm.filesystem import is_junction


def test_missing_path_is_not_a_junction(tmp_path):
    assert not is_junction(tmp_path / "new-plugin")


def test_regular_directory_is_not_a_junction(tmp_path):
    assert not is_junction(tmp_path)
