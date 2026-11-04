"""A lease opener preserves exclusive creation and does not leak locks into children."""

import os

import pytest

from pm.filesystem import open_lease_fd


def test_lease_fd_is_private_and_preserves_existing_contents(tmp_path):
    path = tmp_path / "lease"
    fd = open_lease_fd(path, create=True)
    try:
        assert not os.get_inheritable(fd)
        os.write(fd, b"owner")
        with pytest.raises(FileExistsError):
            open_lease_fd(path, create=True)
    finally:
        os.close(fd)
    assert path.read_bytes() == b"owner"
    with pytest.raises(FileNotFoundError):
        open_lease_fd(tmp_path / "missing")
