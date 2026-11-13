"""List protocols can play white noise: a line with "noise" in place of the kHz."""

import json
import unittest
from unittest import mock

from boombox import protocol_tab as tab, protocols
from tests.helpers import TempDir, make_session, run_session, short_protocol

QUIET_VOLUME = mock.patch("boombox.sysutil.output_volume", return_value=(50, False))


class NoiseLineTests(unittest.TestCase):
    def test_lines_are_read_as_tones_or_noise(self):
        self.assertEqual(tab.parse_list_line("300, noise, 110"),
                         {"time_s": 300.0, "stimulus": "noise", "level_db": 110.0})
        self.assertEqual(tab.parse_list_line("315 NOISE"), {"time_s": 315.0, "stimulus": "noise"})
        self.assertEqual(tab.parse_list_line("330, 8"), {"time_s": 330.0, "freq_hz": 8000.0})
        for bad in ("300", "300, loud", "300, noise, 110, 5", "x, noise"):
            with self.assertRaises((ValueError, IndexError)):
                tab.parse_list_line(bad)

    def test_lines_are_shown_again_as_typed(self):
        for line in ("300, noise, 110", "315, noise", "330, 8", "345, 12, 95"):
            self.assertEqual(tab._list_line_text(tab.parse_list_line(line)), line)

    def test_schedule_and_calibration_check_use_noise(self):
        p = short_protocol(trials=[{"time_s": 0.3, "stimulus": "noise", "level_db": 90.0},
                                   {"time_s": 0.6, "freq_hz": 12000}])
        trials, _ = protocols.build_schedule(p)
        self.assertEqual([t["pulse"]["stimulus"] for t in trials], ["noise", "tone"])
        self.assertEqual(trials[0]["pulse"]["level_db"], 90.0)
        self.assertEqual(trials[1]["pulse"]["freq_hz"], 12000.0)
        used = protocols.stimuli_used(p)
        self.assertEqual([s["stimulus"] for s in used], ["noise", "tone"])
        self.assertIn("noise", protocols.describe_schedule(trials, 1.0))

    def test_generator_accepts_noise(self):
        self.assertEqual(tab._gen_item(" noise "), "noise")
        self.assertEqual(tab._gen_item("8"), 8.0)

    @QUIET_VOLUME
    def test_session_records_noise_without_a_frequency(self, _vol):
        p = short_protocol(trials=[{"time_s": 0.3, "stimulus": "noise"},
                                   {"time_s": 0.6, "freq_hz": 12000}])
        with TempDir() as d:
            s, engine, cam, logs = make_session(d, protocol=p)
            try:
                run_session(s)
            finally:
                cam.stop()
            self.assertEqual(s.state, "done")
            info = json.loads((s.folder / f"{s.base}_info.json").read_text(encoding="utf-8"))
            noise, tone = info["stimuli"]
            self.assertEqual(noise["pulse_stimulus"], "noise")
            self.assertNotIn("pulse_freq_hz", noise)
            self.assertEqual(tone["pulse_freq_hz"], 12000.0)


if __name__ == "__main__":
    unittest.main()
