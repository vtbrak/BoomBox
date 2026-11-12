"""Test runs keep their temporary files on the project drive and clean up after themselves."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from tests import scratch
from tests.helpers import TempDir


class ScratchTests(unittest.TestCase):
    def test_temporary_files_go_in_this_runs_folder(self):
        self.assertEqual(Path(tempfile.gettempdir()), scratch.RUN_DIR)
        self.assertEqual(scratch.RUN_DIR.parent, scratch.ROOT)
        with TempDir() as d:
            self.assertEqual(d.parent, scratch.RUN_DIR)
        self.assertFalse(d.exists())

    def test_folders_from_killed_runs_are_removed_later(self):
        old = scratch.ROOT / "run-killed-test"
        recent = scratch.ROOT / "run-recent-test"
        try:
            for folder in (old, recent):
                (folder / "inside").mkdir(parents=True, exist_ok=True)
            long_ago = time.time() - scratch.STALE_S - 60
            os.utime(old, (long_ago, long_ago))
            scratch._remove_stale_runs()
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())       # might belong to a run still going
            self.assertTrue(scratch.RUN_DIR.exists())
        finally:
            for folder in (old, recent):
                if folder.exists():
                    for p in sorted(folder.rglob("*"), reverse=True):
                        p.rmdir()
                    folder.rmdir()


if __name__ == "__main__":
    unittest.main()
