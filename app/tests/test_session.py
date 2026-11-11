import csv
import json
import os
import subprocess
import sys
import textwrap
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from boombox import session as session_mod
from boombox import stimuli
from tests.helpers import TempDir, make_session, run_session

ROOT = Path(__file__).resolve().parent.parent
QUIET_VOLUME = mock.patch("boombox.sysutil.output_volume", return_value=(50, False))


class SessionFileTests(unittest.TestCase):
    @QUIET_VOLUME
    def test_full_session_writes_every_file(self, _vol):
        with TempDir() as d:
            from tests.helpers import short_protocol
            ref = "https://doi.org/10.1523/JNEUROSCI.1313-25.2026"
            s, engine, cam, logs = make_session(d, protocol=short_protocol(reference=ref))
            try:
                run_session(s)
            finally:
                cam.stop()
            self.assertEqual(s.state, "done")
            names = sorted(p.name for p in s.folder.iterdir())
            base = s.base
            for suffix in ("_Side.mp4", "_info.json", "_info.csv", "_Side_frames.csv",
                           "_trials.csv", "_events.log"):
                self.assertIn(base + suffix, names)
            info = json.loads((s.folder / f"{base}_info.json").read_text(encoding="utf-8"))
            cam_entry = info["cameras"][0]
            self.assertEqual(cam_entry["frames"], cam_entry["verified_frames_in_file"])
            self.assertEqual([x["pulse_freq_hz"] for x in info["stimuli"]], [8000.0, 12000.0])
            self.assertEqual(info["boom_box"]["protocol_reference"], ref)
            self.assertIn(ref, (s.folder / f"{base}_events.log").read_text(encoding="utf-8"))
            with open(s.folder / f"{base}_Side_frames.csv", encoding="utf-8") as f:
                self.assertEqual(sum(1 for _ in f) - 1, cam_entry["frames"])

    def test_text_files_are_utf8_on_any_computer(self):
        # Windows' default file encoding can't hold every name; files must be written as UTF-8.
        script = textwrap.dedent("""
            from unittest import mock
            from tests.helpers import TempDir, make_session, run_session
            with mock.patch("boombox.sysutil.output_volume", return_value=(50, False)), TempDir() as d:
                meta = {"experimenter": "Zoë Łukasz 实验员", "animal_id": "M01", "sex": "F",
                        "notes": "Größe ✓"}
                s, engine, cam, logs = make_session(d, meta=meta)
                try:
                    run_session(s)
                finally:
                    cam.stop()
                for p in s.folder.iterdir():
                    if p.suffix in (".csv", ".log", ".json"):
                        p.read_text(encoding="utf-8")
                print("OK", s.state)
        """)
        env = dict(os.environ, PYTHONWARNDEFAULTENCODING="1")
        res = subprocess.run([sys.executable, "-W", "error::EncodingWarning", "-c", script],
                             cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertIn("OK done", res.stdout, res.stderr[-2000:])


class SessionFailureTests(unittest.TestCase):
    @QUIET_VOLUME
    def test_session_stops_when_the_video_encoder_dies(self, _vol):
        with TempDir() as d:
            s, engine, cam, logs = make_session(d)
            try:
                s.start()
                time.sleep(0.2)
                s.recorder._proc.kill()              # e.g. disk full
                deadline = time.time() + 5
                stopped = False
                while time.time() < deadline:
                    if s.poll():
                        stopped = True
                        break
                    time.sleep(0.02)
                self.assertTrue(stopped, "poll() never reported the failure")
                self.assertTrue(s.stopped_early)
                self.assertTrue(any("video" in m.lower() for m in logs))
                s.stop(early=True)
                with self.assertRaises(RuntimeError):
                    s.finalize()
            finally:
                cam.stop()
            # The stimulus timing must survive even though the video didn't.
            names = [p.name for p in s.folder.iterdir()]
            self.assertEqual(s.state, "failed")
            self.assertIn(f"{s.base}_trials.csv", names)
            self.assertIn(f"{s.base}_events.log", names)
            self.assertTrue(any(n.endswith("_frames.csv") for n in names))

    def test_failed_start_releases_the_microphone(self):
        class FakeMic:
            def __init__(self, device, path):
                self.device_name, self.fs, self.stopped = device, 48000, False

            def start(self):
                pass

            def stop(self):
                self.stopped = True

        mics = []

        def fake_mic(*a):
            mics.append(FakeMic(*a))
            return mics[-1]

        with TempDir() as d, \
                mock.patch.object(session_mod, "MicRecorder", side_effect=fake_mic), \
                mock.patch.object(session_mod, "VideoRecorder", side_effect=OSError("ffmpeg not found")):
            s, engine, cam, logs = make_session(d, mic_device="Fake mic")
            try:
                with self.assertRaises(OSError):
                    s.start()
            finally:
                cam.stop()
        self.assertTrue(mics and mics[0].stopped, "microphone was left recording")
        self.assertIsNone(cam.recorder)


class MicAudioTests(unittest.TestCase):
    FS = 48000

    def _session_with_raw_mic(self, folder, seconds, tones=()):
        rng = np.random.default_rng(0)
        x = (rng.standard_normal(int(seconds * self.FS)) * 0.002).astype(np.float32)
        for f0, t in tones:
            w = stimuli.tone_burst(f0, -20, 5, 0, 5, self.FS)
            i = int((t + 0.003) * self.FS)
            x[i:i + w.size] += w
        sf.write(folder / "_mic_raw.wav", x, self.FS, subtype="PCM_24")
        s = session_mod.Session.__new__(session_mod.Session)
        s.folder, s.t0 = folder, 100.0
        return s, x

    def test_aligned_audio_matches_the_mic_recording(self):
        with TempDir() as d:
            s, x = self._session_with_raw_mic(d, 30)
            fit = (99.5, (1 / self.FS) * (1 + 50e-6))   # mic started 0.5 s early, clock 50 ppm slow
            s._write_aligned_audio(d / "aligned.wav", fit, 20.0)
            out, fs = sf.read(d / "aligned.wav", dtype="float32")
        self.assertEqual(fs, self.FS)
        self.assertEqual(out.size, 20 * self.FS)
        raw = sf.read  # noqa: F841 (keeps the reference below easy to read)
        m = np.arange(out.size, dtype=np.float64)
        ref = np.interp((s.t0 + m / fs - fit[0]) / fit[1], np.arange(x.size), x.astype(np.float64))
        self.assertLess(np.max(np.abs(out - ref)), 1e-5)

    def test_aligning_a_long_recording_doesnt_load_it_all_into_memory(self):
        # A 30-minute protocol makes a mic file of hundreds of MB; aligning it must stream.
        with TempDir() as d:
            s, x = self._session_with_raw_mic(d, 120)
            del x
            tracemalloc.start()
            s._write_aligned_audio(d / "aligned.wav", (100.0, 1 / self.FS), 110.0)
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
        self.assertLess(peak, 15e6, f"used {peak / 1e6:.0f} MB for a 23 MB recording")

    def test_mic_onset_detection(self):
        with TempDir() as d:
            s, _ = self._session_with_raw_mic(d, 10, tones=[(4000, 2.0), (12000, 5.0), (20000, 8.0)])
            fit = (100.0, 1 / self.FS)
            s._write_aligned_audio(d / "aligned.wav", fit, 10.0)
            for f0, t in [(4000, 2.0), (12000, 5.0), (20000, 8.0)]:
                on = s._detect_onset({"stimulus": "tone", "freq_hz": f0, "rise_ms": 5, "plateau_ms": 0},
                                     100 + t, fit)
                self.assertIsNotNone(on)
                self.assertAlmostEqual((on - 100 - t) * 1000, 3.0, delta=0.5)
            silent = s._detect_onset({"stimulus": "tone", "freq_hz": 8000, "rise_ms": 5, "plateau_ms": 0},
                                     100 + 6.5, fit)
            self.assertIsNone(silent)


if __name__ == "__main__":
    unittest.main()
