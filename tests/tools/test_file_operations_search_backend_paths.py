"""A remote Git root must keep its backend's path spelling."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from tools.file_operations import ShellFileOperations
from tools.file_operations_common import ExecuteResult


def test_gitignore_keeps_remote_posix_root_on_every_controller():
    ops = ShellFileOperations(SimpleNamespace(cwd="/c/repo"))
    ops._exec = MagicMock(side_effect=[
        ExecuteResult(stdout="true", exit_code=0),
        ExecuteResult(stdout="/c/repo/ignored\0", exit_code=0),
    ])
    assert ops._filter_gitignored_paths(["/c/repo/ignored", "/c/repo/visible"], "/c/repo") == ["/c/repo/visible"]
    assert "git -C '/c/repo'" in ops._exec.call_args_list[0].args[0]
