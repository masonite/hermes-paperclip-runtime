"""Consistent file metadata for path and descriptor version checks."""

import os
import stat
from pathlib import Path


def stat_file(path: str | os.PathLike[str]) -> os.stat_result:
    metadata = Path(path).stat()
    # Windows path stat reports creation time as ctime; fstat reports change time.
    if os.name == "nt" and stat.S_ISREG(metadata.st_mode):
        with open(path, "rb") as stream:
            return os.fstat(stream.fileno())
    return metadata
