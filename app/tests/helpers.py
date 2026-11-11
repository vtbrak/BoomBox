"""Stand-ins for the camera and sound card, so sessions can run in tests without hardware.

The video encoder is the real one (ffmpeg from the conda environment), so the
files a session writes are real files.
"""

import collections
import copy
import shutil
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from boombox import audio, calibration, config, protocols

W, H, FPS = 64, 48, 30


class FakeEngine:
    """Plays nothing; marks each scheduled stimulus as played when its time comes."""

    def __init__(self):
        self.fs = 48000
        self.actual_device = "Test output"
        self.channel_mode = "both"
        self.clip_count = self.underflow_count = 0
        self.noise_target = 0.0
        self.finished = collections.deque()
        self._timers = []

    def set_noise_dbfs(self, dbfs):
        self.noise_target = 0.0 if dbfs is None else 10 ** (dbfs / 20)

    def schedule(self, wave, start_perf, tag=None):
        ev = audio.StimEvent(start_perf=start_perf, wave=np.asarray(wave, np.float32), tag=tag or {})

        def play():
            if not ev.cancelled:
                ev.actual_perf = start_perf
                ev.pos = ev.wave.size
            self.finished.append(ev)

        timer = threading.Timer(max(0.0, start_perf - time.perf_counter()), play)
        timer.daemon = True
        timer.start()
        self._timers.append(timer)
        return ev


class FakeCamera:
    """Sends small grey frames at a steady rate to whatever recorder is attached."""

    has_settings_dialog = False

    def __init__(self, fps=FPS):
        self.name = "Test camera"
        self.width, self.height, self.fps = W, H, fps
        self.latency_s = 0.0
        self.error = None
        self.recorder = None
        self.frame_count = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def alive(self):
        return self._thread.is_alive()

    def _run(self):
        n = 0
        while not self._stop.is_set():
            frame = np.full((self.height, self.width), n % 256, np.uint8)
            rec = self.recorder
            if rec is not None:
                rec.push(frame, time.perf_counter())
            self.frame_count += 1
            n += 1
            time.sleep(1.0 / self.fps)

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)


def short_protocol(**changes):
    """Two quiet tones about a third of a second apart; about one second in all."""
    p = copy.deepcopy(protocols.BUILTINS[protocols.TVS_NAME])
    p.update(name="Test", builtin=False, background_noise_db=None, end_padding_s=0.3)
    p["trials"] = [{"time_s": 0.3, "freq_hz": 8000}, {"time_s": 0.6, "freq_hz": 12000}]
    p.update(changes)
    return p


def make_session(data_dir, protocol=None, meta=None, **setting_changes):
    from boombox.session import Session
    protocol = protocol or short_protocol()
    trials, total = protocols.build_schedule(protocol)
    settings = dict(config.DEFAULT_SETTINGS, data_dir=str(data_dir), mic_device="")
    settings.update(setting_changes)
    engine, cam = FakeEngine(), FakeCamera()
    logs = []
    session = Session(engine=engine, camera=cam, cal=calibration.empty_calibration(), protocol=protocol,
                      trials=trials, total_s=total,
                      meta=meta or {"experimenter": "Tester", "animal_id": "T1", "sex": "U"},
                      settings=settings, uvc_values={}, log=logs.append)
    return session, engine, cam, logs


def run_session(session, timeout=15):
    """Start, run to the end (or until poll() says stop), stop and save."""
    session.start()
    deadline = time.time() + timeout
    while not session.poll():
        if time.time() > deadline:
            raise TimeoutError("session did not finish")
        time.sleep(0.02)
    session.stop(early=session.stopped_early)
    session.finalize()


class TempDir:
    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix="boombox_test_"))
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
