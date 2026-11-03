"""Linux desktop entries are not installed on the other native hosts."""

import pytest

from hermes_cli import linux_desktop_entry as lde
from tests.hermes_cli.test_linux_desktop_entry import _make_project


@pytest.mark.platforms("macos")
def test_install_is_a_noop_on_macos(tmp_path):
    assert lde.install_desktop_entry(_make_project(tmp_path)) is None


@pytest.mark.platforms("windows")
def test_install_is_a_noop_on_windows(tmp_path):
    assert lde.install_desktop_entry(_make_project(tmp_path)) is None
