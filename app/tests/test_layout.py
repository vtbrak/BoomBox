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
            (app / "config" / "protocols").mkdir(parents=True)
            (main / "protocols" / "Same.json").write_text('{"name": "Same"}')
            (app / "config" / "protocols" / "Same.json").write_text('{"name": "Same"}')

            with mock.patch.multiple(config, OLD_CONFIG_DIR=main / "config", CONFIG_DIR=app / "config",
                                     OLD_PROTOCOL_DIR=main / "protocols",
                                     USER_PROTOCOL_DIR=app / "config" / "protocols"):
                config.migrate_old_layout()

            self.assertEqual(json.loads((app / "config" / "settings.json").read_text()), {"arena": "ASR2"})
            self.assertTrue((app / "config" / "calibration_history" / "c1.json").exists())
            self.assertTrue((app / "config" / "protocols" / "My_list.json").exists())
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
                                     OLD_PROTOCOL_DIR=main / "protocols",
                                     USER_PROTOCOL_DIR=app / "config" / "protocols"):
                config.migrate_old_layout()
            self.assertEqual(json.loads((app / "config" / "settings.json").read_text()), {"arena": "NEW"})
            # The differing old copy is kept rather than deleted.
            self.assertTrue((main / "config" / "settings.json").exists())



class DataFolderTests(unittest.TestCase):
    """The data folder moves with the program instead of pointing back at an old copy."""

    def patched(self, main):
        return mock.patch.multiple(config, MAIN_DIR=main, DEFAULT_DATA_DIR=main / "Data",
                                   SETTINGS_PATH=main / "app" / "config" / "settings.json")

    def test_data_folder_inside_the_main_folder_is_saved_relative(self):
        with TempDir() as d:
            old, new = d / "BoomBox-1.3.6", d / "BoomBox-1.3.7"
            with self.patched(old):
                config.save_settings(dict(config.DEFAULT_SETTINGS, data_dir=str(old / "Data")))
                saved = json.loads((old / "app" / "config" / "settings.json").read_text())
                self.assertEqual(saved["data_dir"], "Data")
            # The user copies app/config into the new version.
            (new / "app" / "config").mkdir(parents=True)
            (new / "app" / "config" / "settings.json").write_text(
                (old / "app" / "config" / "settings.json").read_text())
            with self.patched(new):
                self.assertEqual(config.load_settings()["data_dir"], str(new / "Data"))

    def test_data_folder_elsewhere_stays_a_full_path(self):
        with TempDir() as d:
            main, elsewhere = d / "BoomBox", d / "Lab data"
            elsewhere.mkdir()
            with self.patched(main):
                config.save_settings(dict(config.DEFAULT_SETTINGS, data_dir=str(elsewhere)))
                self.assertEqual(config.load_settings()["data_dir"], str(elsewhere))
                self.assertIsNone(config.data_dir_problem(str(elsewhere)))

    def test_problems_from_copied_settings_are_found(self):
        with TempDir() as d:
            old, new = d / "BoomBox-old", d / "BoomBox-new"
            for folder in (old, new):
                (folder / "app" / "boombox").mkdir(parents=True)
            (old / "Data").mkdir()
            with self.patched(new):
                # Still pointing into the old copy: sessions would quietly go there.
                self.assertIn("another Boom Box folder", config.data_dir_problem(str(old / "Data")))
                # The old copy was deleted.
                self.assertIn("can't be found", config.data_dir_problem(str(d / "gone" / "Data")))
                # This copy's own Data folder is fine, even before the first session creates it.
                self.assertIsNone(config.data_dir_problem(str(new / "Data")))


if __name__ == "__main__":
    unittest.main()
