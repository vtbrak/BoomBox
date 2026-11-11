"""Folder locations and persistent settings (app/config/settings.json).

The main Boom Box folder holds only what a user opens (start and install files,
README, INSTALL, Data); the program, protocols and settings live in its app/ folder.
"""

import copy
import filecmp
import json
import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent      # .../Boom Box/app
MAIN_DIR = APP_DIR.parent                             # .../Boom Box
CONFIG_DIR = APP_DIR / "config"
PROTOCOL_DIR = APP_DIR / "protocols"
DEFAULT_DATA_DIR = MAIN_DIR / "Data"
# Before Boom Box 1.3.3 these sat in the main folder.
OLD_CONFIG_DIR = MAIN_DIR / "config"
OLD_PROTOCOL_DIR = MAIN_DIR / "protocols"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
CALIBRATION_PATH = CONFIG_DIR / "calibration.json"
CALIBRATION_HISTORY_DIR = CONFIG_DIR / "calibration_history"

ADD_NAME_LABEL = "Add a name"

DEFAULT_SETTINGS = {
    "experimenters": [],
    "last_experimenter": "",
    "data_dir": str(DEFAULT_DATA_DIR),
    "last_protocol": "Tone Volume Sensitivity",
    # Audio
    "output_device": "",          # "" = system default output
    "channel_mode": "both",       # both | left | right
    "sample_rate": 48000,
    "mic_device": "",             # "" = no microphone recording
    "keep_noise_after_session": True,
    # Camera
    "camera_name": "",
    "resolution": "1280x720",
    "fps": 30,
    "camera_latency_ms": 0.0,
    "camera_controls": {},        # UVC control name -> value
    "camera_controls_locked": False,
    "video_crf": 18,
    "video_preset": "veryfast",
    # Track Tamer metadata (set once per rig)
    "arena": "ASR1",
    "room": "",
    "camera_label": "Side",
    # Session
    "countdown_s": 5,
    "calibration_max_age_days": 30,
}


def _merge_into(old, new):
    """Move everything in folder `old` into `new` without replacing anything already there.

    Files that are identical in both are dropped from `old`; `old` is removed once empty.
    """
    new.mkdir(parents=True, exist_ok=True)
    for item in old.iterdir():
        dest = new / item.name
        if not dest.exists():
            shutil.move(str(item), str(dest))
        elif item.is_dir() and dest.is_dir():
            _merge_into(item, dest)
        elif item.is_file() and dest.is_file() and filecmp.cmp(item, dest, shallow=False):
            item.unlink()
    try:
        old.rmdir()
    except OSError:           # something differs and was kept: leave it for the user
        pass


def migrate_old_layout():
    """Carry settings, calibration and custom protocols over from the old folder layout."""
    for old, new in ((OLD_CONFIG_DIR, CONFIG_DIR), (OLD_PROTOCOL_DIR, PROTOCOL_DIR)):
        if old.is_dir():
            _merge_into(old, new)


def ensure_dirs():
    migrate_old_layout()
    for d in (CONFIG_DIR, PROTOCOL_DIR, CALIBRATION_HISTORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return copy.deepcopy(default)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_settings():
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(load_json(SETTINGS_PATH, {}))
    return settings


def save_settings(settings):
    save_json(SETTINGS_PATH, settings)
