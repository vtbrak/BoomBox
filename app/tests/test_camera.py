"""Which capture class is used, and the test pattern runs at the asked frame rate."""

import time
import unittest
from unittest import mock

from boombox import camera


class CameraChoiceTests(unittest.TestCase):
    def test_real_cameras_use_opencv(self):
        # ffmpeg's AVFoundation input picked a slow 10 fps mode at 1280x720, so real
        # cameras are read through OpenCV on both systems.
        with mock.patch.object(camera, "camera_index", return_value=0):
            cam = camera.make_camera("Global Shutter Camera", 1280, 720, 30)
        self.assertIsInstance(cam, camera.CVCamera)
        # The driver settings window exists on Windows only; Macs use USB controls.
        self.assertEqual(cam.has_settings_dialog, camera.IS_WINDOWS)

    def test_test_pattern_uses_ffmpeg(self):
        cam = camera.make_camera(camera.TEST_PATTERN, 320, 240, 30)
        self.assertIsInstance(cam, camera.TestPatternCamera)
        self.assertNotIn("avfoundation", cam._command())

    def test_test_pattern_delivers_frames_at_the_asked_rate(self):
        cam = camera.make_camera(camera.TEST_PATTERN, 320, 240, 30)
        cam.start()
        try:
            # ffmpeg sends a short burst at the start; the rate is measured over the
            # last 3 s, so wait until the burst has left that window.
            deadline = time.time() + 15
            while cam.frame_count < 135 and time.time() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(cam.frame_count, 135, cam.stderr_text())
            self.assertEqual(cam.latest.shape, (240, 320))
            self.assertAlmostEqual(cam.measured_fps(), 30, delta=3)
        finally:
            cam.stop()


if __name__ == "__main__":
    unittest.main()
