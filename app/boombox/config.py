"""Folder locations and persistent settings (app/config/settings.json).

The main Boom Box folder holds only what a user opens (start and install files,
README, INSTALL, Data); the program, protocols and settings live in its app/ folder.

Everything the user sets up (settings, calibration, their own protocols) is in
app/config, so copying that one folder carries it to a new version. The data
folder is saved relative to the main folder when it's inside it, so it moves
with the program instead of pointing back at an old copy.
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
PROTOCOL_DIR = APP_DIR / "protocols"                  # built-in protocols (rewritten by the program)
USER_PROTOCOL_DIR = CONFIG_DIR / "protocols"          # the user's own protocols
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
    if OLD_PROTOCOL_DIR.is_dir():
        # Old copies of built-in protocols aren't needed: the program writes current ones.
        for f in OLD_PROTOCOL_DIR.glob("*.json"):
            if load_json(f, {}).get("builtin"):
                f.unlink()
    for old, new in ((OLD_CONFIG_DIR, CONFIG_DIR), (OLD_PROTOCOL_DIR, USER_PROTOCOL_DIR)):
        if old.is_dir():
            _merge_into(old, new)


def ensure_dirs():
    migrate_old_layout()
    for d in (CONFIG_DIR, PROTOCOL_DIR, USER_PROTOCOL_DIR, CALIBRATION_HISTORY_DIR):
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


def resolve_data_dir(value):
    """The data folder as a full path (a saved relative path is inside the main folder)."""
    if not value:
        return str(DEFAULT_DATA_DIR)
    p = Path(value)
    return str(p if p.is_absolute() else MAIN_DIR / p)


def portable_data_dir(value):
    """The data folder as saved: relative when it's inside the main folder (e.g. "Data")."""
    p = Path(value)
    for base in (MAIN_DIR, MAIN_DIR.resolve()):
        for path in (p, p.resolve()):
            try:
                rel = path.relative_to(base)
            except ValueError:
                continue
            return rel.as_posix() if rel.parts else "."
    return str(p)


def _is_boom_box_folder(path):
    return (Path(path) / "app" / "boombox").is_dir()


def data_dir_problem(value):
    """Why the saved data folder should be checked before recording, or None.

    Two cases come from installing a new version and copying the old settings: the
    folder was in the old copy, which has been deleted, or it still points into the
    old copy, so new sessions would quietly be saved there.
    """
    p = Path(resolve_data_dir(value))
    if p == DEFAULT_DATA_DIR:
        return None
    if not p.is_dir():
        return (f"The data folder can't be found:\n{p}\n\nIt may have been in an older Boom Box "
                "folder that was deleted, or on a drive that isn't connected.")
    if _is_boom_box_folder(p.parent) and p.parent.resolve() != MAIN_DIR.resolve():
        return (f"The data folder is inside another Boom Box folder:\n{p}\n\nThis usually means "
                "the settings were copied from an older version.")
    return None


def load_settings():
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(load_json(SETTINGS_PATH, {}))
    settings["data_dir"] = resolve_data_dir(settings.get("data_dir"))
    return settings


def save_settings(settings):
    data = dict(settings, data_dir=portable_data_dir(resolve_data_dir(settings.get("data_dir"))))
    save_json(SETTINGS_PATH, data)
