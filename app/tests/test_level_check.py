"""The level check: one row per sound, a clear verdict, and short session-start lines."""

import datetime as dt
import tkinter as tk
import unittest

from boombox import calibration, level_check, protocols


def calibrated(tones=(4000, 8000, 12000, 16000, 20000), noise=True, tone_ref=118.0, noise_ref=108.0):
    cal = calibration.empty_calibration()
    for f in tones:
        calibration.set_measurement(cal, f, -20, tone_ref - 20)
    if noise:
        calibration.set_measurement(cal, "noise", -30, noise_ref - 30)
    cal["date"] = (dt.datetime.now() - dt.timedelta(days=2, hours=1)).isoformat(timespec="seconds")
    cal["mac_volume"] = 50
    return cal


def rows(result):
    return {r["sound"]: r for r in result["rows"]}


class LevelCheckTests(unittest.TestCase):
    def test_uncalibrated_says_so_once_and_calls_nothing_too_loud(self):
        cal = calibration.empty_calibration()
        r = level_check.check(cal, protocols.load(protocols.IO_NAME))
        self.assertEqual((r["verdict"], r["headline"]), (level_check.WARN, "Not calibrated"))
        self.assertEqual(list(rows(r)), ["White-noise burst", "Background noise"])
        self.assertTrue(all(level_check.spare_text(x) == "unknown until calibrated" for x in r["rows"]))
        self.assertEqual(level_check.problem_lines(cal, protocols.load(protocols.IO_NAME)), ([], []))
        self.assertEqual(level_check.calibration_line(cal), "No calibration saved yet.")

    def test_levels_beyond_the_speaker_are_named_with_the_fix(self):
        cal = calibrated(noise_ref=108.0)        # noise can reach 108 - 12 = 96 dB
        r = level_check.check(cal, protocols.load(protocols.IO_NAME))
        self.assertEqual(r["verdict"], level_check.BAD)
        self.assertEqual(r["headline"], "3 levels are louder than the speaker can play")
        self.assertIn("White-noise burst at 100, 110 and 120 dB", r["advice"])
        self.assertIn(level_check.FIX_TOO_LOUD, r["advice"])
        burst = rows(r)["White-noise burst"]
        self.assertEqual(level_check.spare_text(burst), "120 dB is 24 dB too loud")
        self.assertEqual(level_check.spare_text(rows(r)["Background noise"]), "31 dB to spare")
        errors, warnings = level_check.problem_lines(cal, protocols.load(protocols.IO_NAME))
        self.assertEqual(len(errors), 1)          # one line per sound, not per level
        self.assertEqual(warnings, [])

    def test_ready_with_one_row_per_sound(self):
        r = level_check.check(calibrated(tone_ref=120.0), protocols.load(protocols.HEARING_NAME))
        self.assertEqual((r["verdict"], r["headline"]), (level_check.OK, "Ready"))
        tone = rows(r)["8 kHz tone"]
        self.assertEqual(len(tone["levels"]), 11)
        self.assertEqual(tone["calibration"], "measured")
        self.assertEqual(level_check.spare_text(tone), "0 dB to spare")

    def test_estimated_and_unmeasured_sounds(self):
        cal = calibrated(tones=(4000, 12000), noise=False)
        r = level_check.check(cal, protocols.load("PPI Default"))
        self.assertEqual(list(rows(r)), ["8 kHz tone", "White-noise prepulse", "Background noise"])
        self.assertEqual(rows(r)["8 kHz tone"]["calibration"], "estimated")
        self.assertEqual(r["headline"], "Some sounds aren't calibrated")
        self.assertIn("White-noise prepulse and Background noise", r["advice"])
        errors, warnings = level_check.problem_lines(cal, protocols.load("PPI Default"))
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 3)

    def test_calibration_line(self):
        line = level_check.calibration_line(calibrated(tones=(4000, 8000)))
        self.assertIn("(2 days old)", line)
        self.assertIn("50", line)
        self.assertTrue(line.endswith("white noise and 4, 8 kHz measured"))

    def test_window(self):
        root = tk.Tk()
        root.withdraw()
        try:
            w = level_check.LevelCheckWindow(root, calibrated(noise_ref=108.0), protocols.load(protocols.IO_NAME),
                                             mono_font="Courier")
            self.assertIn("louder than the speaker", w.headline["text"])
            self.assertEqual(len(w.table.get_children()), 2)
            self.assertFalse(w.detail.winfo_manager())
            w.var_detail.set(True)
            w._toggle_detail()
            self.assertTrue(w.detail.winfo_manager())
            self.assertIn("120 dB SPL  ->    12.0 dBFS", w.detail.get("1.0", "end"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
