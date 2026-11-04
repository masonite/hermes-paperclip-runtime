"""Model snippets use LF even when a local file stores CRLF."""

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


def test_lf_snippet_matches_complete_crlf_line(tmp_path):
    path = tmp_path / "document.txt"
    path.write_bytes(b"line 1\r\nline 10\r\nline 11\r\n")
    env = LocalEnvironment(cwd=str(tmp_path))
    try:
        result = ShellFileOperations(env, cwd=str(tmp_path)).patch_replace(
            str(path), "line 1\n", "changed 1\n")
        assert result.success, result.error
        assert path.read_bytes() == b"changed 1\r\nline 10\r\nline 11\r\n"
    finally:
        env.cleanup()
