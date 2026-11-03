"""A completed local read must survive Windows path/handle timestamp differences."""

import os

import pytest

from tools.file_tools_read_tracking import _file_metadata, _file_version


@pytest.mark.platforms("windows")
def test_stable_file_version_matches_path_metadata(tmp_path):
    path = tmp_path / "document.txt"
    path.touch()
    path.write_bytes(b"current content\n")
    version = _file_version(str(path))
    assert version is not None
    assert version[:-1] == _file_metadata(str(path))

    before = path.stat()
    path.write_bytes(b"changed content\n")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = _file_version(str(path))
    assert changed is not None and changed != version
