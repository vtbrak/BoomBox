"""Folder locations and persistent settings (config/settings.json)."""

import copy
import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = APP_DIR / "config"
PROTOCOL_DIR = APP_DIR / "protocols"
DEFAULT_DATA_DIR = APP_DIR / "Data"
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


def ensure_dirs():
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
