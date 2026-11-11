import json
import unittest
from unittest import mock

import numpy as np

from boombox import calibration, config, gui, protocols, stimuli
from tests.helpers import TempDir


class ProtocolTests(unittest.TestCase):
    def test_builtin_schedules(self):
        tvs, total = protocols.build_schedule(protocols.BUILTINS[protocols.TVS_NAME])
        self.assertEqual([t["ref_time_s"] for t in tvs][:2], [300, 337])
        hab, _ = protocols.build_schedule(protocols.BUILTINS[protocols.HABITUATION_NAME])
        self.assertEqual(len(hab), 100)
        hearing, _ = protocols.build_schedule(protocols.BUILTINS[protocols.HEARING_NAME])
        levels = [t["pulse"]["level_db"] for t in hearing]
        self.assertEqual(levels[:10], [40, 50, 60, 70, 80, 90, 100, 110, 120, 120])
        self.assertEqual(len(levels), 36)

    def test_save_refuses_a_name_that_would_overwrite_another_protocol(self):
        # "Hearing_Test" and "Hearing Test" share a file name; saving one must not replace the other.
        with TempDir() as d, mock.patch.object(config, "PROTOCOL_DIR", d):
            protocols.ensure_builtin()
            clash = dict(protocols.DEFAULT_LIST, name="Hearing_Test")
            with self.assertRaises(ValueError):
                protocols.save(clash)
            on_disk = json.loads((d / "Hearing_Test.json").read_text())
            self.assertEqual(on_disk["name"], protocols.HEARING_NAME)
            # Saving a protocol again under its own name is still fine.
            mine = dict(protocols.DEFAULT_LIST, name="My list")
            protocols.save(mine)
            protocols.save(dict(mine, end_padding_s=10.0))
            self.assertEqual(protocols.load("My list")["end_padding_s"], 10.0)

    def test_new_protocol_with_an_existing_name_doesnt_replace_it(self):
        with TempDir() as d, mock.patch.object(config, "PROTOCOL_DIR", d), \
                mock.patch.object(gui.simpledialog, "askstring", return_value="PPI Default"), \
                mock.patch.object(gui.messagebox, "showerror") as shown:
            protocols.ensure_builtin()
            before = (d / "PPI_Default.json").read_text()
            app = mock.Mock()
            gui.App._new_protocol(app, protocols.DEFAULT_LIST)
            self.assertEqual((d / "PPI_Default.json").read_text(), before)
            shown.assert_called_once()
            app.refresh_protocol_list.assert_not_called()

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
