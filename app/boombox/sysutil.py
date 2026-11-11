"""Operating-system helpers: system volume, keeping the computer awake, disk space."""

import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
VOLUME_LABEL = "Windows volume" if IS_WINDOWS else "Mac volume"


def output_volume():
    """(volume 0-100, muted) or (None, None) if unavailable."""
    if IS_WINDOWS:
        return _windows_volume()
    try:
        out = subprocess.run(["osascript", "-e", "get volume settings"], capture_output=True,
                             encoding="utf-8", errors="replace", timeout=5).stdout
        parts = dict(p.strip().split(":", 1) for p in out.strip().split(","))
        vol = parts.get("output volume", "missing value")
        return (None if vol == "missing value" else int(vol)), parts.get("output muted") == "true"
    except Exception:
        return None, None


def _windows_volume():
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        try:
            comtypes.CoInitialize()      # needed when called from a worker thread
        except OSError:
            pass
        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)
        if endpoint is None:             # older pycaw
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(iface, POINTER(IAudioEndpointVolume))
        return int(round(endpoint.GetMasterVolumeLevelScalar() * 100)), bool(endpoint.GetMute())
    except Exception:
        return None, None


class _WindowsAwake:
    """Keeps Windows from sleeping or turning off the display until terminate()."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002

    def __init__(self):
        import ctypes
        self._k32 = ctypes.windll.kernel32
        self._k32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED
                                          | self.ES_DISPLAY_REQUIRED)

    def terminate(self):
        self._k32.SetThreadExecutionState(self.ES_CONTINUOUS)


def keep_awake():
    """Prevent display/system sleep while this program runs. Returns an object with terminate()."""
    try:
        if IS_WINDOWS:
            return _WindowsAwake()
        return subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())])
    except Exception:
        return None


def free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1e9
    except Exception:
        return None
