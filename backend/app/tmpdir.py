"""Keep scratch files off a full system drive.

PuLP shells out to CBC, which writes a problem file and a solution file per
solve. On this machine C: has no free space, so those writes fail and every
scheduling request returns a 500 — a disk fault that surfaces as an application
error, which is a slow thing to diagnose from the outside.

Importing this module points Python's temp directory at a writable location
before any solve happens. GRIDSENSE_TMPDIR overrides; otherwise it looks for a
drive with room and falls back to the platform default, so this is a no-op on a
healthy machine and in CI.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

#: Enough headroom for a large LP's problem and solution files.
MIN_FREE_BYTES = 512 * 1024 * 1024

CANDIDATES = [Path(r"D:\tmp\gs-solver"), Path("/tmp/gs-solver")]


def _usable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(path).free >= MIN_FREE_BYTES
    except OSError:
        return False


def ensure_writable_tmpdir() -> str:
    """Point tempfile at somewhere with space. Returns the directory in use.

    A configured candidate wins over the platform default even when the default
    has room: on this machine C: hovers near empty, so "enough space right now"
    is not a safe test — a single large solve can exhaust it mid-run.
    """
    override = os.getenv("GRIDSENSE_TMPDIR")
    chosen = None
    if override and _usable(Path(override)):
        chosen = Path(override)
    else:
        chosen = next((c for c in CANDIDATES if _usable(c)), None)

    if chosen is None:
        # No preferred location available; keep the platform default and let the
        # caller deal with whatever space it has.
        return str(Path(tempfile.gettempdir()))

    # CBC is a subprocess and reads the environment, so setting tempfile.tempdir
    # alone would not reach it.
    for var in ("TMPDIR", "TEMP", "TMP"):
        os.environ[var] = str(chosen)
    tempfile.tempdir = str(chosen)
    return str(chosen)
