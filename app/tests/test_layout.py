"""Settings and protocols from the old folder layout carry over into app/."""

import json
import unittest
from unittest import mock

from boombox import config
from tests.helpers import TempDir


class OldLayoutTests(unittest.TestCase):
    def test_old_settings_and_custom_protocols_move_into_app(self):
        with TempDir() as main:
            app = main / "app"
            (main / "config" / "calibration_history").mkdir(parents=True)
            (main / "config" / "settings.json").write_text('{"arena": "ASR2"}')
            (main / "config" / "calibration_history" / "c1.json").write_text("{}")
            (main / "protocols").mkdir()
            (main / "protocols" / "My_list.json").write_text('{"name": "My list"}')
            # An old built-in that differs from the current one is dropped, not left behind.
            (main / "protocols" / "Tone_Volume_Sensitivity.json").write_text(
                '{"name": "Tone Volume Sensitivity", "builtin": true, "old": 1}')
            (app / "protocols").mkdir(parents=True)
            (main / "protocols" / "Hearing_Test.json").write_text('{"name": "Hearing Test"}')
            (app / "protocols" / "Hearing_Test.json").write_text('{"name": "Hearing Test"}')

            with mock.patch.multiple(config, OLD_CONFIG_DIR=main / "config", CONFIG_DIR=app / "config",
                                     OLD_PROTOCOL_DIR=main / "protocols", PROTOCOL_DIR=app / "protocols"):
                config.migrate_old_layout()

            self.assertEqual(json.loads((app / "config" / "settings.json").read_text()), {"arena": "ASR2"})
            self.assertTrue((app / "config" / "calibration_history" / "c1.json").exists())
            self.assertTrue((app / "protocols" / "My_list.json").exists())
            self.assertFalse((main / "config").exists())
            self.assertFalse((main / "protocols").exists())

    def test_nothing_already_in_app_is_replaced(self):
        with TempDir() as main:
            app = main / "app"
            (main / "config").mkdir()
            (main / "config" / "settings.json").write_text('{"arena": "OLD"}')
            (app / "config").mkdir(parents=True)
            (app / "config" / "settings.json").write_text('{"arena": "NEW"}')
            with mock.patch.multiple(config, OLD_CONFIG_DIR=main / "config", CONFIG_DIR=app / "config",
                                     OLD_PROTOCOL_DIR=main / "protocols", PROTOCOL_DIR=app / "protocols"):
                config.migrate_old_layout()
            self.assertEqual(json.loads((app / "config" / "settings.json").read_text()), {"arena": "NEW"})
            # The differing old copy is kept rather than deleted.
            self.assertTrue((main / "config" / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
