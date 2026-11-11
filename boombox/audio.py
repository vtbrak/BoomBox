"""Audio output (background noise, calibration tones, scheduled stimuli) and mic recording.

All times are on the time.perf_counter() clock. PortAudio callback timestamps
are converted to that clock inside each callback, so a stimulus scheduled for
perf time T starts on the exact sample that reaches the DAC at T.
"""

import collections
import queue
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import soundfile as sf

from .stimuli import db_to_amp


IS_WINDOWS = sys.platform == "win32"
WASAPI = "Windows WASAPI"


def _hostapi_name(dev):
    return sd.query_hostapis(dev["hostapi"])["name"]


def _label(dev):
    """Name shown in Settings. Windows lists each device once per audio system, so add it."""
    return f"{dev['name']} [{_hostapi_name(dev)}]" if IS_WINDOWS else dev["name"]


def _devices(key):
    devs = [d for d in sd.query_devices() if d[key] > 0]
    if IS_WINDOWS:
        # WASAPI first: it reports the most accurate output/input timestamps.
        devs.sort(key=lambda d: _hostapi_name(d) != WASAPI)
    return devs


def list_output_devices():
    return [_label(d) for d in _devices("max_output_channels")]


def list_input_devices():
    return [_label(d) for d in _devices("max_input_channels")]


def _device_index(name, kind):
    key = "max_output_channels" if kind == "output" else "max_input_channels"
    if not name:
        if IS_WINDOWS:   # default device of WASAPI rather than the older MME system
            for api in sd.query_hostapis():
                if api["name"] == WASAPI:
                    idx = api["default_output_device" if kind == "output" else "default_input_device"]
                    if idx >= 0:
                        return idx
        return None
    for i, d in enumerate(sd.query_devices()):
        if d[key] > 0 and name in (_label(d), d["name"]):
            return i
    raise ValueError(f"Audio device not found: {name}")


def _extra_settings(dev_index):
    """Let WASAPI convert the sample rate instead of refusing a non-matching one."""
    if not IS_WINDOWS or dev_index is None or _hostapi_name(sd.query_devices(dev_index)) != WASAPI:
        return None
    try:
        return sd.WasapiSettings(auto_convert=True)
    except TypeError:
        return None


@dataclass
class StimEvent:
    start_perf: float
    wave: np.ndarray
    tag: dict = field(default_factory=dict)
    pos: int = 0
    actual_perf: float = None
    late_s: float = 0.0
    cancelled: bool = False


class AudioEngine:
    """Continuously running output stream; mixes noise, calibration tone and stimuli."""

    RAMP_S = 0.1

    def __init__(self, device_name="", sample_rate=48000, channel_mode="both"):
        self.device_name = device_name
        self.fs = int(sample_rate)
        self.channel_mode = channel_mode
        self._stream = None
        self._rng = np.random.default_rng()
        self._new_events = collections.deque()
        self._active = []
        self.finished = collections.deque()
        self.noise_target = 0.0     # linear RMS
        self._noise_cur = 0.0
        self.cal_freq = 0.0
        self.cal_target = 0.0       # linear peak
        self._cal_cur = 0.0
        self._cal_phase = 0.0
        self.clip_count = 0
        self.underflow_count = 0

    # -- stream control -------------------------------------------------
    def start(self):
        dev = _device_index(self.device_name, "output")
        info = sd.query_devices(dev if dev is not None else sd.default.device[1])
        self.n_channels = min(2, info["max_output_channels"])
        if self.channel_mode == "left" or self.n_channels == 1:
            self._chans = [0]
        elif self.channel_mode == "right":
            self._chans = [1]
        else:
            self._chans = list(range(self.n_channels))
        self.actual_device = _label(info)
        self._stream = sd.OutputStream(
            samplerate=self.fs, device=dev, channels=self.n_channels, dtype="float32",
            latency="low", callback=self._callback, extra_settings=_extra_settings(dev))
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def running(self):
        return self._stream is not None and self._stream.active

    # -- public controls ------------------------------------------------
    def set_noise_dbfs(self, dbfs):
        """dbfs=None turns background noise off (with a short ramp)."""
        self.noise_target = 0.0 if dbfs is None else db_to_amp(dbfs)

    def set_cal_tone(self, freq_hz, dbfs):
        """Continuous calibration tone; dbfs=None turns it off."""
        if dbfs is None:
            self.cal_target = 0.0
        else:
            if self._cal_cur == 0.0:
                self._cal_phase = 0.0
            self.cal_freq = float(freq_hz)
            self.cal_target = db_to_amp(dbfs)

    def schedule(self, wave, start_perf, tag=None):
        ev = StimEvent(start_perf=start_perf, wave=np.asarray(wave, np.float32), tag=tag or {})
        self._new_events.append(ev)
        return ev

    def play_now(self, wave, tag=None):
        return self.schedule(wave, time.perf_counter() + 0.05, tag)

    def cancel_all(self):
        for ev in list(self._new_events) + list(self._active):
            ev.cancelled = True

    # -- callback ---------------------------------------------------------
    def _ramp(self, cur, target, frames):
        step = max(cur, target) * frames / (self.RAMP_S * self.fs)
        end = target if abs(target - cur) <= step else cur + np.sign(target - cur) * step
        return np.linspace(cur, end, frames, endpoint=False, dtype=np.float32), float(end)

    def _callback(self, outdata, frames, time_info, status):
        if status.output_underflow:
            self.underflow_count += 1
        now = time.perf_counter()
        cur = time_info.currentTime or (self._stream.time if self._stream else 0.0)
        dac = time_info.outputBufferDacTime
        block_perf = (dac + (now - cur)) if (dac and cur) else now
        buf = np.zeros(frames, np.float32)

        if self.noise_target > 0 or self._noise_cur > 0:
            gains, self._noise_cur = self._ramp(self._noise_cur, self.noise_target, frames)
            buf += self._rng.standard_normal(frames, dtype=np.float32) * gains

        if self.cal_target > 0 or self._cal_cur > 0:
            gains, self._cal_cur = self._ramp(self._cal_cur, self.cal_target, frames)
            w = 2 * np.pi * self.cal_freq / self.fs
            ph = self._cal_phase + w * np.arange(frames)
            buf += (np.sin(ph) * gains).astype(np.float32)
            self._cal_phase = float((ph[-1] + w) % (2 * np.pi))

        while self._new_events:
            self._active.append(self._new_events.popleft())
        still = []
        for ev in self._active:
            if ev.cancelled:
                self.finished.append(ev)
                continue
            offset = 0
            if ev.pos == 0:
                offset = int(round((ev.start_perf - block_perf) * self.fs))
                if offset >= frames:
                    still.append(ev)
                    continue
                if offset < 0:
                    ev.late_s = -offset / self.fs
                    offset = 0
                ev.actual_perf = block_perf + offset / self.fs
            n = min(frames - offset, ev.wave.size - ev.pos)
            buf[offset:offset + n] += ev.wave[ev.pos:ev.pos + n]
            ev.pos += n
            if ev.pos >= ev.wave.size:
                self.finished.append(ev)
            else:
                still.append(ev)
        self._active = still

        peak = np.abs(buf).max() if frames else 0.0
        if peak > 1.0:
            self.clip_count += 1
            np.clip(buf, -1.0, 1.0, out=buf)
        outdata.fill(0)
        for ch in self._chans:
            outdata[:, ch] = buf


class MicRecorder:
    """Records one microphone channel to WAV, remembering the perf time of each block."""

    def __init__(self, device_name, path):
        self.device_name = device_name
        self.path = str(path)
        dev = _device_index(device_name, "input")
        info = sd.query_devices(dev)
        self.fs = int(info["default_samplerate"])
        self._dev = dev
        self._q = queue.Queue()
        self.block_times = []    # (first sample index, perf time of that sample)
        self.n_samples = 0
        self.level_db = -120.0
        self.overflow_count = 0
        self._thread = None
        self._stream = None

    def start(self):
        self._file = sf.SoundFile(self.path, "w", self.fs, 1, "PCM_24")
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()
        self._stream = sd.InputStream(samplerate=self.fs, device=self._dev, channels=1,
                                      dtype="float32", callback=self._callback,
                                      extra_settings=_extra_settings(self._dev))
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        if status.input_overflow:
            self.overflow_count += 1
        now = time.perf_counter()
        cur = time_info.currentTime or (self._stream.time if self._stream else 0.0)
        adc = time_info.inputBufferAdcTime
        t = (adc + (now - cur)) if (adc and cur) else now - frames / self.fs
        self.block_times.append((self.n_samples, t))
        self.n_samples += frames
        data = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(data ** 2))) if frames else 0.0
        self.level_db = 20 * np.log10(max(rms, 1e-6))
        self._q.put(data)

    def _writer(self):
        while True:
            data = self._q.get()
            if data is None:
                break
            self._file.write(data)

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._thread is not None:
            self._q.put(None)
            self._thread.join()
            self._thread = None
            self._file.close()

    def clock_fit(self):
        """Linear fit perf_time = a + b * sample_index (absorbs mic clock drift)."""
        bt = np.array(self.block_times, dtype=np.float64)
        if len(bt) < 2:
            return (bt[0, 1] if len(bt) else 0.0), 1.0 / self.fs
        b, a = np.polyfit(bt[:, 0], bt[:, 1], 1)
        return a, b
