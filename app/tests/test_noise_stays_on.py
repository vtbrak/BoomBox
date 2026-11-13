"""Background noise plays for the whole session in every protocol, including the Hearing Test."""

import json
import unittest
from unittest import mock

from boombox import protocols
from tests.helpers import TempDir, make_session, run_session, short_protocol
from tests.test_protocols_and_levels import protocol_dirs

QUIET_VOLUME = mock.patch("boombox.sysutil.output_volume", return_value=(50, False))
OLD_KEY = "background_noise_off_s"


class NoiseStaysOnTests(unittest.TestCase):
    def test_hearing_test_steps_from_70_to_120_db_in_noise(self):
        p = protocols.BUILTINS[protocols.HEARING_NAME]
        self.assertEqual(p["background_noise_db"], 65.0)
        trials, _ = protocols.build_schedule(p)
        levels = [t["pulse"]["level_db"] for t in trials]
        up = [70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120]
        self.assertEqual(levels, (up + up[::-1]) * 2)
        self.assertEqual(trials[0]["ref_time_s"], 315.0)

    def test_no_built_in_protocol_turns_the_noise_off(self):
        for name, p in protocols.BUILTINS.items():
            self.assertNotIn(OLD_KEY, p, name)
            self.assertIsNotNone(p["background_noise_db"], name)

    def test_an_older_saved_protocol_loses_its_noise_off_time(self):
        with protocol_dirs() as (_, user_dir):
            user_dir.mkdir(parents=True)
            old = dict(protocols.DEFAULT_LIST, name="Old quiet list", **{OLD_KEY: 300.0})
            (user_dir / "Old_quiet_list.json").write_text(json.dumps(old))
            loaded = protocols.load("Old quiet list")
            self.assertNotIn(OLD_KEY, loaded)
            protocols.save(dict(loaded, **{OLD_KEY: 10.0}))
            saved = json.loads((user_dir / "Old_quiet_list.json").read_text())
            self.assertNotIn(OLD_KEY, saved)

    @QUIET_VOLUME
    def test_noise_is_still_on_when_the_session_ends(self, _vol):
        # Even a protocol dict that still carries the old setting doesn't stop the noise.
        p = short_protocol(background_noise_db=65.0, **{OLD_KEY: 0.1})
        with TempDir() as d:
            s, engine, cam, logs = make_session(d, protocol=p)
            try:
                run_session(s)
            finally:
                cam.stop()
        self.assertEqual(s.state, "done")
        self.assertGreater(engine.noise_target, 0)
        self.assertFalse(any("noise off" in line.lower() for line in logs))


if __name__ == "__main__":
    unittest.main()
