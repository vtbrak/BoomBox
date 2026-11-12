"""Clap test: measure the camera's latency from claps seen by the camera and heard by the mic.

A clap happens at one instant for both. The microphone gives its time to a
fraction of a millisecond; the first video frame that shows the hands touching
arrives one camera latency later (plus, on average, half a frame, because the
clap falls at a random point between two frames). So

    latency = (arrival time of that frame) - (clap time) - half a frame

averaged over several claps. This module is the arithmetic and the short
recording; the window is in clap_window.py.
"""

import math
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import MicRecorder

RECORD_S = 15
MIN_GAP_S = 0.7            # claps closer together than this count as one
MAX_FRAME_BYTES = 200e6    # memory for the kept (shrunk) frames


def find_claps(audio, fs, min_gap_s=MIN_GAP_S):
    """Sample index where each clap starts: sudden sounds well above the room noise."""
    x = np.abs(np.asarray(audio, dtype=np.float64))
    if x.size == 0:
        return []
    peak = float(x.max())
    floor = float(np.median(x))
    if peak < 0.01 or peak < 20 * max(floor, 1e-6):      # nothing that stands out
        return []
    loud = 0.3 * peak
    gap = int(min_gap_s * fs)
    back = int(0.005 * fs)                                # a clap rises within a few ms
    claps, i = [], 0
    hits = np.flatnonzero(x >= loud)
    while i < len(hits):
        hit = int(hits[i])
        # Step back to where the sound first rose above a tenth of the loud level.
        start = max(0, hit - back)
        early = np.flatnonzero(x[start:hit + 1] >= 0.1 * loud)
        claps.append(start + int(early[0]))
        i = int(np.searchsorted(hits, hit + gap))
    return claps


def latency_ms(frame_time, clap_time, fps):
    """Camera latency from one clap: the first frame showing it, less half a frame."""
    return (frame_time - clap_time - 0.5 / fps) * 1000.0


def summarize(values):
    """(mean, standard deviation, count) of the latency values in ms."""
    v = [float(x) for x in values]
    if not v:
        return None, None, 0
    mean = sum(v) / len(v)
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
    return mean, sd, len(v)


class FrameCollector:
    """Stands in for the video recorder: keeps shrunk copies of the frames and their times."""

    def __init__(self, width, height, fps, seconds=RECORD_S, latency_s=0.0):
        n = int(fps * (seconds + 1))
        step = 1
        while (width // step) * (height // step) * n > MAX_FRAME_BYTES:
            step += 1
        self.step = step
        self.latency_s = latency_s      # added back: the test needs raw arrival times
        self.frames, self.times = [], []
        self._lock = threading.Lock()

    def push(self, frame, t):
        small = np.ascontiguousarray(frame[::self.step, ::self.step])
        with self._lock:
            self.frames.append(small)
            self.times.append(t + self.latency_s)

    def index_at(self, t):
        """The last frame that arrived at or before perf time t (0 if none)."""
        return max(0, int(np.searchsorted(self.times, t, side="right")) - 1)


class ClapRecording:
    """Records the camera and the microphone together for a few seconds."""

    def __init__(self, cam, mic_device, seconds=RECORD_S):
        self.cam, self.seconds = cam, seconds
        self.frames = FrameCollector(cam.width, cam.height, cam.fps, seconds, cam.latency_s)
        self._dir = tempfile.TemporaryDirectory(prefix="boombox_clap_")
        self._wav = Path(self._dir.name) / "clap.wav"
        self.mic = MicRecorder(mic_device, self._wav)
        self.clap_times = []            # perf time of each clap
        self.t_start = None

    def start(self):
        self.mic.start()
        self.cam.recorder = self.frames
        self.t_start = time.perf_counter()

    def remaining(self):
        return max(0.0, self.seconds - (time.perf_counter() - self.t_start))

    def cancel(self):
        if self.cam.recorder is self.frames:
            self.cam.recorder = None
        self.mic.stop()
        self._dir.cleanup()

    def finish(self):
        """Stop, find the claps, and return how many there were."""
        if self.cam.recorder is self.frames:
            self.cam.recorder = None
        self.mic.stop()
        try:
            audio, fs = sf.read(str(self._wav), dtype="float32")
            a, b = self.mic.clock_fit()
            self.clap_times = [a + b * i for i in find_claps(audio, fs)]
        finally:
            self._dir.cleanup()
        times = self.frames.times
        # Only claps with video on both sides can be measured.
        if times:
            self.clap_times = [t for t in self.clap_times if times[0] < t < times[-1] - 0.3]
        else:
            self.clap_times = []
        return len(self.clap_times)
