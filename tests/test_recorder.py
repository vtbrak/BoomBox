import time
import unittest

import numpy as np

from boombox.camera import VideoRecorder
from tests.helpers import FPS, H, W, TempDir


def frame(n=0):
    return np.full((H, W), n % 256, np.uint8)


class RecorderTests(unittest.TestCase):
    def test_repeats_frames_the_camera_dropped(self):
        with TempDir() as d:
            rec = VideoRecorder(d / "v.mp4", W, H, FPS)
            period = 1.0 / FPS
            for i in (0, 1, 2, 6, 7):          # frames 3-5 never arrive
                rec.push(frame(i), 100 + i * period)
            rc, _ = rec.close()
        self.assertEqual(rc, 0)
        self.assertEqual(rec.n_frames, 8)
        self.assertEqual(rec.duplicated, [0, 0, 0, 1, 1, 1, 0, 0])
        self.assertEqual(len(rec.gaps), 1)
        self.assertEqual((rec.gaps[0]["frame"], rec.gaps[0]["missing"]), (3, 3))
        self.assertAlmostEqual(rec.gaps[0]["time_s"], 6 * period)

    def test_frame_at_finds_the_frame_on_screen(self):
        with TempDir() as d:
            rec = VideoRecorder(d / "v.mp4", W, H, FPS)
            for i in range(10):
                rec.push(frame(i), 10 + i / FPS)
            rec.close()
        self.assertEqual(rec.frame_at(9.0), -1)
        self.assertEqual(rec.frame_at(10.0), 0)
        self.assertEqual(rec.frame_at(10.0 + 2.5 / FPS), 2)
        self.assertEqual(rec.frame_at(99.0), 9)

    def test_frames_pushed_after_close_are_ignored(self):
        # The camera thread can hand over one last frame just as the session closes the
        # recorder; it must not be counted, or the logs list a frame the video doesn't have.
        with TempDir() as d:
            rec = VideoRecorder(d / "v.mp4", W, H, FPS)
            rec.push(frame(0), 1.0)
            rec.close()
            rec.push(frame(1), 1.0 + 1 / FPS)
        self.assertEqual(rec.n_frames, 1)

    def test_encoder_failure_is_detected_and_frames_stop_piling_up(self):
        # If ffmpeg dies (e.g. the disk is full), frames must not keep queueing in memory.
        with TempDir() as d:
            rec = VideoRecorder(d / "missing_folder" / "v.mp4", W, H, FPS)
            i, deadline = 0, time.time() + 5     # ffmpeg only fails once frames arrive
            while not rec.failed and time.time() < deadline:
                rec.push(frame(i), 1.0 + i / FPS)
                i += 1
                time.sleep(0.01)
            self.assertTrue(rec.failed)
            counted = rec.n_frames
            for j in range(60):
                rec.push(frame(j), 10.0 + j / FPS)
            time.sleep(0.3)
            self.assertEqual(rec.n_frames, counted)
            self.assertEqual(rec._q.qsize(), 0)
            rc, _ = rec.close()
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
