"""USB camera capture and constant-frame-rate MP4 recording.

Cameras are read through OpenCV: AVFoundation on macOS, DirectShow on Windows
(which also gives access to the camera's own settings window and its
exposure/gain/focus properties). On macOS the camera's settings are set over
USB instead (uvc.py). ffmpeg is not used for camera capture on macOS because it
picks the last camera mode that matches the size: for cameras that list a slow
uncompressed 1280x720 mode after the fast compressed one, that capped
recordings at 10 fps. The test pattern comes from ffmpeg.

Frames are timestamped on arrival with time.perf_counter() (minus a
configurable camera latency). The recorder keeps the output locked to the wall
clock: if the camera drops frames the previous frame is repeated (and logged),
so frame N in the MP4 is at N / fps seconds and lines up with the audio track.
"""

import bisect
import collections
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

IS_WINDOWS = sys.platform == "win32"
TEST_PATTERN = "Test pattern (no camera)"
MODE_RE = re.compile(r"(\d+)x(\d+)@\[([\d.]+) ([\d.]+)\]fps")
DSHOW_MODE_RE = re.compile(r"max s=(\d+)x(\d+) fps=([\d.]+)")
RESOLUTIONS = {
    "A  800x600": "800x600",
    "B  1280x720 (recommended)": "1280x720",
    "C  1280x960": "1280x960",
    "D  1600x1200": "1600x1200",
    "E  1920x1080": "1920x1080",
    "F  1920x1200": "1920x1200",
}
FPS_CHOICES = [30, 60, 90]
# Don't show a console window for each ffmpeg call on Windows.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


def ffmpeg_path():
    if IS_WINDOWS:
        p = Path(sys.prefix) / "Library" / "bin" / "ffmpeg.exe"
    else:
        p = Path(sys.prefix) / "bin" / "ffmpeg"
    return str(p) if p.exists() else (shutil.which("ffmpeg") or "ffmpeg")


def _ffmpeg_stderr(args):
    # ffmpeg prints UTF-8; decoding with the Windows default code page would garble
    # camera names with accents, so they would no longer match.
    return subprocess.run([ffmpeg_path(), "-hide_banner", *args], capture_output=True,
                          encoding="utf-8", errors="replace", timeout=20, **_NO_WINDOW).stderr


def _measured_fps(times):
    """Frames per second over the recent frame times (0 until there are enough)."""
    if len(times) < 10:
        return 0.0
    span = times[-1] - times[0]
    return (len(times) - 1) / span if span > 0 else 0.0


def _dshow_devices():
    """[(name, alternative name)] of DirectShow video devices, in index order."""
    out = _ffmpeg_stderr(["-list_devices", "true", "-f", "dshow", "-i", "dummy"])
    devices, in_video = [], False
    for line in out.splitlines():
        if "DirectShow video devices" in line:          # older ffmpeg layout
            in_video = True
            continue
        if "DirectShow audio devices" in line:
            in_video = False
            continue
        m = re.search(r'"(.+?)"(?:\s+\((\w+)\))?\s*$', line)
        if not m:
            continue
        if "Alternative name" in line:
            if devices and devices[-1][1] is None:
                devices[-1] = (devices[-1][0], m.group(1))
            continue
        kind = m.group(2)
        if kind == "video" or (kind is None and in_video):
            devices.append((m.group(1), None))
    return devices


def list_cameras():
    """Names of the connected video devices, in index order (screens excluded)."""
    if IS_WINDOWS:
        return [name for name, _ in _dshow_devices()]
    out = _ffmpeg_stderr(["-f", "avfoundation", "-list_devices", "true", "-i", ""])
    names, in_video = [], False
    for line in out.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
        elif "AVFoundation audio devices" in line:
            break
        elif in_video:
            m = re.search(r"\[(\d+)\] (.+)$", line)
            if m and not m.group(2).startswith("Capture screen"):
                names.append(m.group(2).strip())
    return names


def camera_index(name):
    names = list_cameras()
    if name not in names:
        raise RuntimeError(f"Camera '{name}' not found. Connected: {', '.join(names) or 'none'}")
    return names.index(name)


def list_modes(name, index=None):
    """[(width, height, max fps)] supported by the camera (pass its index if already known)."""
    if name == TEST_PATTERN:
        return [(int(r.split("x")[0]), int(r.split("x")[1]), f)
                for r in RESOLUTIONS.values() for f in FPS_CHOICES]
    modes = set()
    if IS_WINDOWS:
        out = _ffmpeg_stderr(["-f", "dshow", "-list_options", "true", "-i", f"video={name}"])
        for m in DSHOW_MODE_RE.finditer(out):
            modes.add((int(m.group(1)), int(m.group(2)), float(m.group(3))))
        return sorted(modes)
    idx = camera_index(name) if index is None else index
    out = _ffmpeg_stderr(["-f", "avfoundation", "-framerate", "1000", "-video_size", "1x1",
                          "-i", f"{idx}:none"])
    for m in MODE_RE.finditer(out):
        modes.add((int(m.group(1)), int(m.group(2)), float(m.group(4))))
    return sorted(modes)


def usb_cameras():
    """{camera name: (vendor_id, product_id)} for USB (UVC) cameras."""
    cams = {}
    if IS_WINDOWS:
        try:
            for name, alt in _dshow_devices():
                m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", alt or "", re.I)
                if m:
                    cams[name] = (int(m.group(1), 16), int(m.group(2), 16))
        except Exception:
            pass
        return cams
    try:
        out = subprocess.run(["system_profiler", "SPCameraDataType"], capture_output=True,
                             encoding="utf-8", errors="replace", timeout=20).stdout
    except Exception:
        return {}
    name = None
    for line in out.splitlines():
        s = line.strip()
        if s.endswith(":") and line.startswith("    ") and not line.startswith("      "):
            name = s[:-1]
        m = re.search(r"UVC Camera VendorID_(\d+) ProductID_(\d+)", s)
        if m and name:
            cams[name] = (int(m.group(1)), int(m.group(2)))
    return cams


def default_camera(names):
    """Prefer an external USB camera over built-in, phone and virtual cameras."""
    skip = ("FaceTime", "iPhone", "Integrated", "Virtual", "OBS")
    usb = usb_cameras()
    for n in names:
        if n in usb and not any(k in n for k in skip):
            return n
    for n in names:
        if not any(k in n for k in skip):
            return n
    return names[0] if names else TEST_PATTERN


def make_camera(name, width, height, fps, latency_ms=0.0):
    """The right capture class for this camera (the test pattern comes from ffmpeg)."""
    if name == TEST_PATTERN:
        return TestPatternCamera(name, width, height, fps, latency_ms)
    return CVCamera(name, width, height, fps, latency_ms)


class TestPatternCamera:
    """A moving test picture from ffmpeg, for trying the program without a camera."""

    has_settings_dialog = False

    def __init__(self, name, width, height, fps, latency_ms=0.0):
        self.name = name
        self.width, self.height, self.fps = int(width), int(height), int(fps)
        self.latency_s = float(latency_ms) / 1000.0
        self.frame_bytes = self.width * self.height
        self.latest = None
        self.frame_count = 0
        self.recorder = None
        self.error = None
        self._times = collections.deque(maxlen=self.fps * 3)
        self._stderr = collections.deque(maxlen=40)
        self._proc = None
        self._stop = threading.Event()

    def _command(self):
        src = ["-re", "-f", "lavfi", "-i", f"testsrc2=size={self.width}x{self.height}:rate={self.fps}"]
        return [ffmpeg_path(), "-hide_banner", "-loglevel", "warning", *src,
                "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]

    def start(self):
        cmd = self._command()
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.DEVNULL, bufsize=0, **_NO_WINDOW)
        threading.Thread(target=self._read_stderr, daemon=True).start()
        threading.Thread(target=self._read_frames, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    @property
    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    def measured_fps(self):
        return _measured_fps(self._times)

    def _read_stderr(self):
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode(errors="replace").strip()
            if line:
                self._stderr.append(line)

    def stderr_text(self):
        return "\n".join(self._stderr)

    def _read_frames(self):
        stdout = self._proc.stdout
        while not self._stop.is_set():
            buf = bytearray(self.frame_bytes)
            view, got = memoryview(buf), 0
            while got < self.frame_bytes:
                n = stdout.readinto(view[got:])
                if not n:
                    break
                got += n
            if got < self.frame_bytes:
                break
            t = time.perf_counter() - self.latency_s
            frame = np.frombuffer(buf, np.uint8).reshape(self.height, self.width)
            self.latest = frame
            self.frame_count += 1
            self._times.append(t)
            rec = self.recorder
            if rec is not None:
                rec.push(frame, t)
        if not self._stop.is_set():
            time.sleep(0.2)
            self.error = self.stderr_text() or "Camera stream ended unexpectedly."


class CVCamera:
    """Camera capture through OpenCV (AVFoundation on macOS, DirectShow on Windows).

    The capture device is opened and used only on the capture thread (DirectShow
    objects belong to the thread that created them); camera-setting calls from
    the GUI are queued to that thread. The driver settings window and the
    OpenCV camera properties are used on Windows only; on macOS the GUI sets the
    camera over USB (uvc.py).
    """

    # Properties read when settings are locked and re-applied at every session.
    # Auto modes come first so manual values stick.
    CONTROL_NAMES = ["auto_exposure", "autofocus", "exposure", "gain", "focus", "brightness",
                     "contrast", "gamma", "sharpness", "white_balance"]
    has_settings_dialog = IS_WINDOWS

    def __init__(self, name, width, height, fps, latency_ms=0.0):
        import cv2
        self.cv2 = cv2
        self.props = {"auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE, "autofocus": cv2.CAP_PROP_AUTOFOCUS,
                      "exposure": cv2.CAP_PROP_EXPOSURE, "gain": cv2.CAP_PROP_GAIN,
                      "focus": cv2.CAP_PROP_FOCUS, "brightness": cv2.CAP_PROP_BRIGHTNESS,
                      "contrast": cv2.CAP_PROP_CONTRAST, "gamma": cv2.CAP_PROP_GAMMA,
                      "sharpness": cv2.CAP_PROP_SHARPNESS,
                      "white_balance": cv2.CAP_PROP_WB_TEMPERATURE}
        self.name = name
        self.width, self.height, self.fps = int(width), int(height), int(fps)
        self.latency_s = float(latency_ms) / 1000.0
        self.latest = None
        self.frame_count = 0
        self.recorder = None
        self.error = None
        self._times = collections.deque(maxlen=self.fps * 3)
        self._messages = collections.deque(maxlen=40)
        self._cmds = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._index = camera_index(name)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def measured_fps(self):
        return _measured_fps(self._times)

    def stderr_text(self):
        return "\n".join(self._messages)

    # -- camera settings (run on the capture thread) --------------------------
    def _call(self, fn, timeout=3.0):
        if not self.alive:
            raise RuntimeError("Camera is not running")
        done, box = threading.Event(), {}
        self._cmds.put((fn, done, box))
        if not done.wait(timeout):
            raise RuntimeError("Camera did not respond")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def open_settings_dialog(self):
        """Open the camera driver's own settings window (exposure, gain, focus, ...)."""
        return self._call(lambda cap: cap.set(self.cv2.CAP_PROP_SETTINGS, 1))

    def read_controls(self):
        def read(cap):
            vals = {}
            for n in self.CONTROL_NAMES:
                v = cap.get(self.props[n])
                if v != -1:
                    vals[n] = v
            return vals
        return self._call(read)

    def apply_controls(self, values):
        def apply(cap):
            errors = []
            for n in self.CONTROL_NAMES:
                if n in values and not cap.set(self.props[n], float(values[n])):
                    errors.append(n)
            return errors
        return self._call(apply)

    # -- capture loop -----------------------------------------------------------
    def _run(self):
        cv2 = self.cv2
        cap = cv2.VideoCapture(self._index, cv2.CAP_DSHOW if IS_WINDOWS else cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            self.error = (f"Could not open camera '{self.name}'. Is another program using it, "
                          "or is camera access turned off for Terminal?")
            return
        if IS_WINDOWS:   # macOS picks the compressed (MJPEG) mode itself when it's needed
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        got_w, got_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (got_w, got_h) != (self.width, self.height):
            cap.release()
            self.error = (f"{self.name} does not support {self.width}x{self.height} "
                          f"(it offered {got_w}x{got_h}). Use 'Show camera modes' to see options.")
            return
        try:
            while not self._stop.is_set():
                while not self._cmds.empty():
                    fn, done, box = self._cmds.get()
                    try:
                        box["result"] = fn(cap)
                    except Exception as e:
                        box["error"] = e
                    done.set()
                ok, frame = cap.read()
                if not ok:
                    self.error = "Camera stopped sending video (unplugged or in use by another program)."
                    break
                t = time.perf_counter() - self.latency_s
                gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if gray.shape != (self.height, self.width):
                    gray = cv2.resize(gray, (self.width, self.height))
                self.latest = gray
                self.frame_count += 1
                self._times.append(t)
                rec = self.recorder
                if rec is not None:
                    rec.push(gray, t)
        finally:
            cap.release()


# x264 normally writes a complete picture (keyframe) every 250 frames and, between them,
# reuses still parts of the picture. That freezes the camera's faint grain, which then
# reappears all at once at each keyframe and reads as a burst of movement. Intra-refresh
# renews the picture a column at a time instead, so no frame stands out. Seeking still lands
# on the right frame (each refresh cycle is marked as a recovery point).
X264_PARAMS = "intra-refresh=1"


class VideoRecorder:
    """Encodes pushed frames to H.264 MP4 at a constant frame rate locked to the wall clock."""

    def __init__(self, path, width, height, fps, crf=18, preset="veryfast"):
        self.path = str(path)
        self.width, self.height, self.fps = width, height, fps
        self.period = 1.0 / fps
        self.t0 = None
        self.frame_times = []     # perf time of each written frame
        self.duplicated = []      # 1 if the frame repeats the previous one (camera dropped)
        self.gaps = []            # {"frame", "time_s", "missing"}
        self.skipped = 0          # camera frames discarded because the camera ran fast
        self.max_queue = 0
        self.failed = False       # the encoder stopped (crashed, disk full, ...)
        self._closed = False
        self._lock = threading.Lock()   # push() runs on the camera thread, close() elsewhere
        self._next_slot = 0
        self._last = None
        self._q = queue.Queue()
        cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "pipe:0",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
               "-x264-params", X264_PARAMS, "-pix_fmt", "yuv420p", "-movflags", "+faststart", self.path]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NO_WINDOW)
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def _write(self, frame, t, dup):
        self.frame_times.append(t)
        self.duplicated.append(dup)
        self._q.put(frame)
        self.max_queue = max(self.max_queue, self._q.qsize())
        self._next_slot += 1

    def push(self, frame, t):
        with self._lock:
            if self._closed or self.failed:
                return
            if self._proc.poll() is not None:     # encoder gone: stop queueing frames
                self.failed = True
                return
            self._push(frame, t)

    def _push(self, frame, t):
        if self.t0 is None:
            self.t0 = t
            self._last = frame
            self._write(frame, t, 0)
            return
        err = (t - self.t0) / self.period - self._next_slot
        if err > 1.5:
            # A repeat is a copy of the last picture, so it carries that picture's time
            # (its slot time could fall before the picture it copies).
            missing, last_t = 0, self.frame_times[-1]
            while err > 0.5:
                self._write(self._last, last_t, 1)
                err -= 1
                missing += 1
            self.gaps.append({"frame": self._next_slot - missing,
                              "time_s": t - self.t0, "missing": missing})
        elif err < -1.5:
            self.skipped += 1
            return
        self._last = frame
        self._write(frame, t, 0)

    def _writer(self):
        # Keep taking frames off the queue even after a failure, so they don't pile up in memory.
        while True:
            frame = self._q.get()
            if frame is None:
                break
            if self.failed:
                continue
            try:
                self._proc.stdin.write(frame.tobytes())
            except OSError:          # BrokenPipeError and friends: the encoder has gone
                self.failed = True

    def close(self):
        with self._lock:
            self._closed = True
        self._q.put(None)
        self._thread.join()
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        self._proc.wait()
        err = self._proc.stderr.read().decode(errors="replace").strip()
        return self._proc.returncode, err

    @property
    def n_frames(self):
        return len(self.frame_times)

    @property
    def n_duplicated(self):
        return int(sum(self.duplicated))

    def frame_at(self, t):
        """Index of the frame being exposed at perf time t (-1 if before recording)."""
        return bisect.bisect_right(self.frame_times, t) - 1
