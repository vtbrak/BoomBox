"""The clap test window, driven with a made-up recording (no camera or microphone)."""

import tkinter as tk
import unittest
from unittest import mock

import numpy as np

from boombox import clap_window, claptest


class FakeRecording:
    """Frames every 1/30 s arriving 50 ms late, with claps at 1.0, 2.0 ... 6.0 s."""

    def __init__(self, cam, mic_device, seconds=15):
        self.cam = cam
        self.frames = claptest.FrameCollector(320, 180, 30)
        for i in range(240):
            self.frames.push(np.full((180, 320), i % 255, np.uint8), i / 30 + 0.05)
        self.clap_times = []

    def start(self):
        pass

    def remaining(self):
        return 0.0

    def cancel(self):
        pass

    def finish(self):
        self.clap_times = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        return len(self.clap_times)


class FakeApp:
    def __init__(self, root):
        self.root = root
        self.camera = mock.Mock(width=320, height=180, fps=30, frame_count=5, latency_s=0.0)
        self.settings = {"mic_device": "Fake mic"}
        self.latency = None

    def set_camera_latency(self, ms):
        self.latency = ms


class ClapWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_marking_each_clap_gives_the_latency(self):
        app = FakeApp(self.root)
        with mock.patch.object(claptest, "ClapRecording", FakeRecording):
            w = clap_window.ClapWindow(app)
            w.record()
            self.root.update()
            self.assertIn("Clap 1 of 6", w.var_status.get())
            for _ in range(6):
                # The window opens on the last picture that arrived before the sound;
                # step to the first one exposed at or after the clap (arrives 50 ms later).
                clap = w.rec.clap_times[w.clap]
                while w.rec.frames.times[w.frame] - 0.05 < clap - 1e-9:
                    w.step(1)
                w.mark()
            self.root.update()
        mean, sd, n = claptest.summarize(w.results)
        self.assertEqual(n, 6)
        # Claps sit exactly on a frame here, so each reads 50 ms less half a frame.
        self.assertAlmostEqual(mean, 50 - 1000 / 60, delta=0.5)
        self.assertNotIn("disabled", w.btn_use.state())
        w.use()
        self.assertAlmostEqual(app.latency, round(mean, 1))
        w.close()

    def test_no_microphone_is_explained(self):
        app = FakeApp(self.root)
        app.settings["mic_device"] = ""
        w = clap_window.ClapWindow(app)
        with mock.patch.object(clap_window.messagebox, "showerror") as err:
            w.record()
        self.assertIn("microphone", err.call_args[0][1].lower())
        w.close()


if __name__ == "__main__":
    unittest.main()
