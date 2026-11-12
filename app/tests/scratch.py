"""Keep every temporary file a test run makes on the project drive, and remove it afterwards.

Imported by tests/__init__.py, so it runs before any test. Each run gets its own
folder, app/tests/.tmp/run-XXXX, and Python's temporary-file functions
(mkdtemp, TemporaryDirectory, gettempdir) all use it. It's removed when the run
ends, pass or fail. Folders left by runs that were killed are removed by a later
run once they're 6 hours old. app/tests/.tmp/ is in .gitignore.
"""

import atexit
import shutil
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent / ".tmp"
STALE_S = 6 * 3600


def _remove_stale_runs():
    now = time.time()
    for old in ROOT.glob("run-*"):
        try:
            if old.is_dir() and now - old.stat().st_mtime > STALE_S:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


ROOT.mkdir(exist_ok=True)
_remove_stale_runs()
RUN_DIR = Path(tempfile.mkdtemp(prefix="run-", dir=ROOT))
tempfile.tempdir = str(RUN_DIR)
atexit.register(shutil.rmtree, RUN_DIR, ignore_errors=True)
