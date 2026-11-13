import contextlib
import json
import unittest
from unittest import mock

import numpy as np

from boombox import calibration, config, gui, protocols, stimuli
from tests.helpers import TempDir


@contextlib.contextmanager
def protocol_dirs():
    """Temporary built-in and user protocol folders (the real ones are never touched)."""
    with TempDir() as d:
        builtin_dir, user_dir = d / "protocols", d / "config" / "protocols"
        with mock.patch.multiple(config, PROTOCOL_DIR=builtin_dir, USER_PROTOCOL_DIR=user_dir):
            yield builtin_dir, user_dir

class ProtocolTests(unittest.TestCase):
    def test_builtin_schedules(self):
        tvs, total = protocols.build_schedule(protocols.BUILTINS[protocols.TVS_NAME])
        self.assertEqual([t["ref_time_s"] for t in tvs][:2], [300, 337])
        hab, _ = protocols.build_schedule(protocols.BUILTINS[protocols.HABITUATION_NAME])
        self.assertEqual(len(hab), 100)
        hearing, _ = protocols.build_schedule(protocols.BUILTINS[protocols.HEARING_NAME])
        levels = [t["pulse"]["level_db"] for t in hearing]
        self.assertEqual(levels[:12], [70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 120])
        self.assertEqual(len(levels), 44)

    def test_save_refuses_a_name_that_would_overwrite_another_protocol(self):
        # "My list" and "My_list" share a file name; saving one must not replace the other.
        with protocol_dirs() as (builtin_dir, user_dir):
            protocols.ensure_builtin()
            mine = dict(protocols.DEFAULT_LIST, name="My list")
            protocols.save(mine)
            with self.assertRaises(ValueError):
                protocols.save(dict(protocols.DEFAULT_LIST, name="My_list"))
            self.assertEqual(json.loads((user_dir / "My_list.json").read_text())["name"], "My list")
            # Saving a protocol again under its own name is still fine.
            protocols.save(dict(mine, end_padding_s=10.0))
            self.assertEqual(protocols.load("My list")["end_padding_s"], 10.0)
            # A user protocol can never replace a built-in's file: they're in different folders.
            protocols.save(dict(protocols.DEFAULT_LIST, name="Hearing_Test"))
            self.assertEqual(json.loads((builtin_dir / "Hearing_Test.json").read_text())["name"],
                             protocols.HEARING_NAME)

    def test_user_protocols_live_in_config_and_old_ones_move_there(self):
        with protocol_dirs() as (builtin_dir, user_dir):
            builtin_dir.mkdir()
            # Before 1.3.7 the user's protocols sat next to the built-ins.
            (builtin_dir / "My_list.json").write_text(json.dumps(dict(protocols.DEFAULT_LIST, name="My list")))
            (builtin_dir / "PPI_Default.json").write_text(json.dumps(dict(protocols.DEFAULT_PPI, seed=3)))
            protocols.ensure_builtin()
            self.assertFalse((builtin_dir / "My_list.json").exists())
            self.assertFalse((builtin_dir / "PPI_Default.json").exists())
            self.assertEqual(protocols.load("My list")["name"], "My list")
            self.assertEqual(protocols.load("PPI Default")["seed"], 3)      # the user's edits kept
            self.assertTrue((builtin_dir / "Hearing_Test.json").exists())
            names = protocols.list_protocols()
            self.assertEqual(names[:4], list(protocols.BUILTINS))
            self.assertIn("My list", names)
            protocols.save(dict(protocols.DEFAULT_LIST, name="Another"))
            self.assertTrue((user_dir / "Another.json").exists())
            protocols.delete("Another")
            self.assertFalse((user_dir / "Another.json").exists())

    def test_new_protocol_with_an_existing_name_doesnt_replace_it(self):
        with protocol_dirs() as (_, d), \
                mock.patch.object(gui.simpledialog, "askstring", return_value="PPI Default"), \
                mock.patch.object(gui.messagebox, "showerror") as shown:
            protocols.ensure_builtin()
            before = (d / "PPI_Default.json").read_text()
            app = mock.Mock()
            gui.App._new_protocol(app, protocols.DEFAULT_LIST)
            self.assertEqual((d / "PPI_Default.json").read_text(), before)
            shown.assert_called_once()
            app.refresh_protocol_list.assert_not_called()

    def test_io_schedule(self):
        p = protocols.BUILTINS[protocols.IO_NAME]
        self.assertEqual(p["reference"], "https://doi.org/10.1523/JNEUROSCI.1313-25.2026")
        hab = protocols.BUILTINS[protocols.HABITUATION_NAME]["reference"]
        self.assertIn("https://doi.org/10.3389/fnint.2013.00103", hab)
        self.assertIn("https://doi.org/10.1016/j.jneumeth.2025.110497", hab)    # the 8 kHz choice
        self.assertEqual(protocols.BUILTINS[protocols.TVS_NAME]["reference"],
                         "https://doi.org/10.1016/j.jneumeth.2025.110497")
        self.assertIn("https://iacuc.ucsf.edu/content/acoustic-startle-response",
                      protocols.BUILTINS[protocols.HEARING_NAME]["reference"])
        trials, _ = protocols.build_schedule(p)
        self.assertEqual(len(trials), 35)
        level = lambda t: t["pulse"]["level_db"] if t["pulse"] else None
        for b in range(5):                       # every block has each level once
            block = trials[b * 7:(b + 1) * 7]
            self.assertEqual(sorted(map(str, map(level, block))),
                             sorted(map(str, [70.0, 80.0, 90.0, 100.0, 110.0, 120.0, None])))
        self.assertTrue(all(t["pulse"]["stimulus"] == "noise" for t in trials if t["pulse"]))
        self.assertEqual([t["ref_time_s"] for t in trials[:2]], [300.0, 315.0])
        widths = {round(sum(t["pulse"][k] for k in ("rise_ms", "plateau_ms", "fall_ms")), 6)
                  for t in trials if t["pulse"]}
        self.assertEqual(widths, {40.0})

    def test_builtin_files_are_refreshed_to_this_version(self):
        with protocol_dirs() as (d, _):
            d.mkdir()
            (d / "Hearing_Test.json").write_text(json.dumps(dict(protocols.BUILTINS[protocols.HEARING_NAME],
                                                                 end_padding_s=99)))
            protocols.ensure_builtin()
            self.assertEqual(protocols.load(protocols.HEARING_NAME), protocols.BUILTINS[protocols.HEARING_NAME])
            self.assertEqual(protocols.load(protocols.IO_NAME)["type"], "io")

    def test_ppi_schedule_is_repeatable_with_a_seed(self):
        p = dict(protocols.DEFAULT_PPI, seed=7)
        a, _ = protocols.build_schedule(p)
        b, _ = protocols.build_schedule(p)
        self.assertEqual([t["type"] for t in a], [t["type"] for t in b])


class CalibrationTests(unittest.TestCase):
    def test_level_math(self):
        cal = calibration.empty_calibration()
        calibration.set_measurement(cal, 8000, -30, 85)
        dbfs, status, ok = calibration.stimulus_dbfs(cal, {"stimulus": "tone", "freq_hz": 8000}, 100)
        self.assertEqual((dbfs, status, ok), (-15.0, "calibrated", True))
        dbfs, _, ok = calibration.stimulus_dbfs(cal, {"stimulus": "tone", "freq_hz": 8000}, 120)
        self.assertFalse(ok)

    def test_muted_sound_blocks_a_session_even_before_calibrating(self):
        errors, warnings = gui.volume_problems(calibration.empty_calibration(), 50, True)
        self.assertTrue(any("MUTED" in e for e in errors))

    def test_volume_change_since_calibration_is_a_warning(self):
        cal = calibration.empty_calibration()
        calibration.set_measurement(cal, 8000, -30, 85)
        cal["mac_volume"] = 100
        errors, warnings = gui.volume_problems(cal, 60, False)
        self.assertEqual(errors, [])
        self.assertTrue(any("60" in w and "100" in w for w in warnings))


class CameraValueTests(unittest.TestCase):
    def test_camera_that_wont_answer_doesnt_block_the_session(self):
        class Unresponsive:
            def apply_all(self, values):
                raise RuntimeError("Camera did not respond")

            def read_all(self):
                raise RuntimeError("Camera did not respond")

        values, problem = gui.session_camera_values(Unresponsive(), True, {"gain": 10})
        self.assertEqual(values, {})
        self.assertIn("did not respond", problem)

    def test_camera_values_are_read_after_applying_locked_ones(self):
        class Cam:
            def __init__(self):
                self.vals = {"gain": 1}

            def apply_all(self, values):
                self.vals.update(values)
                return []

            def read_all(self):
                return dict(self.vals)

        values, problem = gui.session_camera_values(Cam(), True, {"gain": 10})
        self.assertEqual((values, problem), ({"gain": 10}, None))


class StimulusTests(unittest.TestCase):
    def test_tone_burst_shape(self):
        w = stimuli.tone_burst(8000, 0, 5, 0, 5, 48000)
        self.assertEqual(w.size, 480)
        self.assertEqual(w[0], 0)
        self.assertLessEqual(np.abs(w).max(), 1.0)


if __name__ == "__main__":
    unittest.main()
