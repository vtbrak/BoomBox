"""Speaker calibration: converts dB SPL targets to dBFS output levels.

For each frequency the experimenter plays a continuous tone at a known dBFS
and types in the level read on a sound level meter. That gives
    ref_db = measured dB SPL - test dBFS   (dB SPL produced at 0 dBFS)
and any target level is then played at  dBFS = target - ref_db.

Tones are calibrated by peak amplitude, so a 10 ms burst is presented at the
same peak level as the continuous calibration tone (peak-equivalent SPL).
Noise is calibrated by RMS.
"""

import datetime as dt
import math

from . import config

# Used until a real measurement exists. Chosen so uncalibrated output is not
# dangerously loud on typical amplifiers; values are flagged as uncalibrated.
UNCALIBRATED_TONE_REF_DB = 120.0
UNCALIBRATED_NOISE_REF_DB = 120.0
NOISE_MAX_DBFS = -12.0   # Gaussian noise peaks ~4x RMS; keep headroom to avoid clipping
TONE_MAX_DBFS = 0.0

DEFAULT_FREQS_HZ = [4000, 8000, 12000, 16000, 20000]


def empty_calibration():
    return {
        "date": None,
        "weighting": "Z",
        "mac_volume": None,
        "output_device": None,
        "channel_mode": None,
        "sample_rate": None,
        "tones": {},    # str(freq_hz) -> {"test_dbfs", "measured_db", "ref_db"}
        "noise": None,  # {"test_dbfs", "measured_db", "ref_db"}
    }


def load():
    cal = empty_calibration()
    cal.update(config.load_json(config.CALIBRATION_PATH, {}))
    return cal


def save(cal):
    cal["date"] = dt.datetime.now().isoformat(timespec="seconds")
    config.save_json(config.CALIBRATION_PATH, cal)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    config.save_json(config.CALIBRATION_HISTORY_DIR / f"calibration_{stamp}.json", cal)


def is_calibrated(cal):
    return bool(cal.get("tones")) or bool(cal.get("noise"))


def age_days(cal):
    if not cal.get("date"):
        return None
    return (dt.datetime.now() - dt.datetime.fromisoformat(cal["date"])).total_seconds() / 86400.0


def tone_ref(cal, freq_hz):
    """Return (ref_db, status). status: calibrated | interpolated | uncalibrated."""
    pts = sorted((float(f), v["ref_db"]) for f, v in cal.get("tones", {}).items())
    if not pts:
        return UNCALIBRATED_TONE_REF_DB, "uncalibrated"
    for f, ref in pts:
        if abs(f - freq_hz) < 1e-6:
            return ref, "calibrated"
    if freq_hz <= pts[0][0]:
        return pts[0][1], "interpolated"
    if freq_hz >= pts[-1][0]:
        return pts[-1][1], "interpolated"
    for (f1, r1), (f2, r2) in zip(pts, pts[1:]):
        if f1 < freq_hz < f2:
            w = (math.log(freq_hz) - math.log(f1)) / (math.log(f2) - math.log(f1))
            return r1 + w * (r2 - r1), "interpolated"
    return pts[-1][1], "interpolated"


def noise_ref(cal):
    if cal.get("noise"):
        return cal["noise"]["ref_db"], "calibrated"
    return UNCALIBRATED_NOISE_REF_DB, "uncalibrated"


def stimulus_dbfs(cal, stim, level_db):
    """dBFS needed to play stim (dict) at level_db dB SPL. Returns (dbfs, status, ok)."""
    if stim.get("stimulus", "tone") == "noise":
        ref, status = noise_ref(cal)
        dbfs = level_db - ref
        return dbfs, status, dbfs <= NOISE_MAX_DBFS
    ref, status = tone_ref(cal, stim["freq_hz"])
    dbfs = level_db - ref
    return dbfs, status, dbfs <= TONE_MAX_DBFS


def set_measurement(cal, key, test_dbfs, measured_db):
    """key: frequency in Hz (number) or 'noise'."""
    entry = {"test_dbfs": float(test_dbfs), "measured_db": float(measured_db),
             "ref_db": float(measured_db) - float(test_dbfs)}
    if key == "noise":
        cal["noise"] = entry
    else:
        cal.setdefault("tones", {})[str(int(key))] = entry
