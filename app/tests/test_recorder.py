import re
import subprocess
import time
import unittest

import numpy as np

from boombox.camera import VideoRecorder, ffmpeg_path
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

    def test_a_repeat_carries_the_time_of_the_picture_it_copies(self):
        # The last real frame arrived late in its slot, so the next slot's time falls
        # before it. Times must never go backwards.
        with TempDir() as d:
            rec = VideoRecorder(d / "v.mp4", W, H, FPS)
            period = 1.0 / FPS
            for t in (0, 1, 2.45, 5):          # frame 2 late; frames for slots 3-4 missing
                rec.push(frame(int(t)), 100 + t * period)
            rec.close()
        self.assertEqual(rec.duplicated, [0, 0, 0, 1, 1, 0])
        self.assertEqual(rec.frame_times[3], rec.frame_times[2])
        self.assertEqual(rec.frame_times[4], rec.frame_times[2])
        self.assertTrue(all(b >= a for a, b in zip(rec.frame_times, rec.frame_times[1:])))

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

    def test_video_has_no_keyframe_bursts(self):
        # Intra-refresh: after the first frame there are no complete keyframes (x264 would
        # otherwise write one every 250 frames, each showing up as a burst of movement).
        rng = np.random.default_rng(1)
        base = rng.integers(60, 200, (H, W), dtype=np.uint8)
        with TempDir() as d:
            rec = VideoRecorder(d / "v.mp4", W, H, FPS)
            for i in range(300):
                grain = rng.integers(-3, 4, (H, W))
                rec.push(np.clip(base + grain, 0, 255).astype(np.uint8), 1.0 + i / FPS)
            rc, err = rec.close()
            self.assertEqual(rc, 0, err)
            out = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(d / "v.mp4"),
                                  "-vf", "showinfo", "-f", "null", "-"],
                                 capture_output=True, text=True).stderr
        types = re.findall(r"type:([IPB])", out)
        self.assertEqual(len(types), 300)
        self.assertEqual(types.count("I"), 1)

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
