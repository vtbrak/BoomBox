"""The running log: one row per session, the suite's columns and words, every column every time."""

import csv
import unittest
from unittest import mock

from boombox import session as session_mod
from tests.helpers import TempDir, make_session, run_session

QUIET_VOLUME = mock.patch("boombox.sysutil.output_volume", return_value=(50, False))

# The same 24 columns, in the same order, as Creature Capture's log.
SUITE_COLUMNS = [
    "date", "start_time", "assay", "assay_variant", "phase", "arena",
    "experimenter", "cohort",
    "animal_id", "sex", "strain", "dob", "treatment", "trial_day", "session_number", "notes",
    "duration_set_min", "duration_actual_s", "stopped_early",
    "frames", "repeated_frames", "videos", "encoder", "app_version",
]


def read_log(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


class RunningLogTests(unittest.TestCase):
    @QUIET_VOLUME
    def test_each_session_adds_a_row_with_every_column(self, _vol):
        with TempDir() as d:
            for animal in ("M01", "M02"):
                # Only the animal ID: strain, cohort, notes etc. are blank but still columns.
                s, engine, cam, logs = make_session(d, meta={"experimenter": "", "animal_id": animal})
                try:
                    run_session(s)
                finally:
                    cam.stop()
                self.assertEqual(s.state, "done")
            cols, rows = read_log(d / f"{d.name}_log.csv")
            self.assertEqual(cols, SUITE_COLUMNS)
            self.assertEqual([r["animal_id"] for r in rows], ["M01", "M02"])
            r = rows[0]
            self.assertEqual(r["assay"], "Acoustic Startle Response")
            self.assertEqual((r["phase"], r["strain"], r["cohort"], r["notes"]), ("", "", "", ""))
            self.assertEqual(r["stopped_early"], "no")
            self.assertTrue(r["videos"].endswith("_Side.mp4"))
            self.assertRegex(r["repeated_frames"], r"^Side:\d+$")
            self.assertEqual(r["encoder"], "libx264")
            self.assertRegex(r["duration_actual_s"], r"^\d+\.\d\d$")
            self.assertEqual(r["sex"], "U")
            self.assertGreater(int(r["frames"]), 0)

    def test_row_waits_while_the_log_is_locked_then_is_added(self):
        with TempDir() as d:
            log = d / "Data_log.csv"
            row = {k: "" for k in SUITE_COLUMNS}
            real = session_mod._append_log_rows
            with mock.patch.object(session_mod, "_append_log_rows", side_effect=PermissionError):
                self.assertFalse(session_mod.append_log(log, dict(row, animal_id="A")))
            self.assertTrue((d / "Data_log_pending.csv").exists())
            with mock.patch.object(session_mod, "_append_log_rows", side_effect=real):
                self.assertTrue(session_mod.append_log(log, dict(row, animal_id="B")))
            self.assertFalse((d / "Data_log_pending.csv").exists())
            _, rows = read_log(log)
            self.assertEqual([r["animal_id"] for r in rows], ["A", "B"])

    def test_log_with_other_columns_is_rewritten_once(self):
        with TempDir() as d:
            log = d / "Data_log.csv"
            log.write_text("date,animal_id,old_column\n2026-01-01,OLD,x\n", encoding="utf-8")
            session_mod.append_log(log, {k: "" for k in SUITE_COLUMNS} | {"animal_id": "NEW"})
            cols, rows = read_log(log)
            self.assertEqual(cols, SUITE_COLUMNS)
            self.assertEqual([(r["date"], r["animal_id"]) for r in rows],
                             [("2026-01-01", "OLD"), ("", "NEW")])


if __name__ == "__main__":
    unittest.main()
