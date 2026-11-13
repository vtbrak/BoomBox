"""Stimulus protocols and schedule generation.

Three protocol types, stored as JSON in protocols/:
  * "list": startle stimuli at listed times (the built-in protocols and custom lists)
  * "ppi":  prepulse inhibition trials generated from editable parameters
  * "io":   input/output curve: each level (plus optional no-stimulus trials) repeated
            in balanced, shuffled blocks at a fixed interval

Every protocol may carry a "reference": the paper(s) or procedure its design comes
from (DOI or web links, with a short note), recorded with each session.

Every built-in protocol starts with a 5-minute habituation in background white
noise, and the noise stays on until the end of the session. (Before 1.3.10 a
protocol could turn it off with "background_noise_off_s"; that setting is now
dropped when a saved protocol is loaded.)

A schedule is a list of trials. Every trial has a reference time (ref_time_s,
from frame 0 of the video) and optional "pulse" and "prepulse" stimuli. For
prepulse+pulse trials the pulse is at the reference time and the prepulse
starts lead_ms earlier; prepulse-alone trials put the prepulse at the
reference time; no-stimulus trials only log the reference time.
"""

import copy
import json
import random
import re

from . import config

HABITUATION_S = 300            # 5 minutes of background noise before the first stimulus
TONE = {"stimulus": "tone", "rise_ms": 5.0, "plateau_ms": 0.0, "fall_ms": 5.0}

# Track Tamer metadata standard: assay is always Acoustic Startle Response;
# the variant comes from the protocol ("" = plain startle, left out of the info file).
ASSAY = "Acoustic Startle Response"
ASSAY_VARIANTS = ["", "Prepulse Inhibition", "Startle Habituation"]

# Tone Volume Sensitivity: the published startle series (first tone at 120 s),
# shifted so the first tone comes right after the 5-minute habituation.
TVS_NAME = "Tone Volume Sensitivity"
TVS_REFERENCE = "https://doi.org/10.1016/j.jneumeth.2025.110497"
TVS_PUBLISHED_TIMES_S = [120, 157, 185, 218, 248, 260, 291, 334, 353, 388, 419, 458, 486, 515, 530]
TVS_TIMES_S = [t - TVS_PUBLISHED_TIMES_S[0] + HABITUATION_S for t in TVS_PUBLISHED_TIMES_S]
TVS_FREQS_KHZ = [12, 4, 16, 20, 8, 4, 20, 16, 12, 8, 8, 16, 4, 20, 12]

HABITUATION_NAME = "Startle Habituation"
HABITUATION_REFERENCE = ("https://doi.org/10.3389/fnint.2013.00103 (habituation design); "
                         f"{TVS_REFERENCE} (choice of the 8 kHz tone at 115 dB)")
HEARING_NAME = "Hearing Test"
HEARING_REFERENCE = "https://iacuc.ucsf.edu/content/acoustic-startle-response (UCSF IACUC standard procedure)"
# 70 dB and up: the 65 dB background noise stays on, and would mask quieter tones.
HEARING_LEVELS_DB = list(range(70, 121, 5))
HEARING_ITI_S = 15.0
# Two ascending and two descending series, alternating.
HEARING_ORDER_DB = (HEARING_LEVELS_DB + HEARING_LEVELS_DB[::-1]) * 2

IO_NAME = "I/O"
IO_REFERENCE = "https://doi.org/10.1523/JNEUROSCI.1313-25.2026"

BUILTINS = {
    TVS_NAME: {
        "name": TVS_NAME, "type": "list", "builtin": True, "assay_variant": "", "reference": TVS_REFERENCE,
        "startle": dict(TONE, level_db=105.0),
        "background_noise_db": 65.0,
        "end_padding_s": 30.0,
        "trials": [{"time_s": t, "freq_hz": f * 1000} for t, f in zip(TVS_TIMES_S, TVS_FREQS_KHZ)],
    },
    HABITUATION_NAME: {
        "name": HABITUATION_NAME, "type": "list", "builtin": True,
        "assay_variant": "Startle Habituation", "reference": HABITUATION_REFERENCE,
        "startle": dict(TONE, level_db=115.0),
        "background_noise_db": 65.0,
        "end_padding_s": 30.0,
        "trials": [{"time_s": HABITUATION_S + 15 * i, "freq_hz": 8000} for i in range(100)],
    },
    HEARING_NAME: {
        "name": HEARING_NAME, "type": "list", "builtin": True, "assay_variant": "",
        "reference": HEARING_REFERENCE,
        "startle": dict(TONE, level_db=80.0),
        "background_noise_db": 65.0,
        "end_padding_s": 30.0,
        "trials": [{"time_s": HABITUATION_S + HEARING_ITI_S * (i + 1), "freq_hz": 8000, "level_db": float(db)}
                   for i, db in enumerate(HEARING_ORDER_DB)],
    },
    # 40 ms noise bursts at 70-120 dB plus a no-stimulus trial, five of each in balanced
    # shuffled blocks, every 15 s, with background noise throughout.
    IO_NAME: {
        "name": IO_NAME, "type": "io", "builtin": True, "assay_variant": "",
        "reference": IO_REFERENCE,
        "background_noise_db": 65.0,
        "acclimation_s": float(HABITUATION_S),
        "end_padding_s": 30.0,
        "pulse": {"stimulus": "noise", "freq_hz": 8000, "rise_ms": 2.0, "plateau_ms": 36.0, "fall_ms": 2.0},
        "levels_db": [70, 80, 90, 100, 110, 120],
        "include_no_stim": True,
        "repeats": 5,
        "iti_s": 15.0,
        "randomize": True,
        "seed": None,
    },
}
LEGACY_BUILTIN_NAMES = ["ASR Standard"]   # old name of Tone Volume Sensitivity
OLD_NOISE_OFF_KEY = "background_noise_off_s"   # before 1.3.10: time to turn the noise off

DEFAULT_LIST = {
    "name": "Custom list",
    "type": "list",
    "assay_variant": "",
    "reference": "",
    "startle": dict(TONE, level_db=105.0),
    "background_noise_db": 65.0,
    "end_padding_s": 30.0,
    "trials": [{"time_s": HABITUATION_S + 30 * i, "freq_hz": 8000} for i in range(10)],
}

DEFAULT_PPI = {
    "name": "PPI Default",
    "type": "ppi",
    "assay_variant": "Prepulse Inhibition",
    "reference": "",
    "background_noise_db": 65.0,
    "acclimation_s": float(HABITUATION_S),
    "end_padding_s": 30.0,
    "pulse": {"stimulus": "tone", "freq_hz": 8000, "level_db": 105.0,
              "rise_ms": 5.0, "plateau_ms": 0.0, "fall_ms": 5.0},
    "prepulse": {"stimulus": "noise", "freq_hz": 8000, "levels_above_bg_db": [3, 6, 12],
                 "rise_ms": 2.0, "plateau_ms": 16.0, "fall_ms": 2.0},
    "lead_intervals_ms": [100],
    "start_pulse_alone": 5,
    "end_pulse_alone": 0,
    "n_pulse_alone": 10,
    "n_prepulse_pulse_each": 10,
    "n_prepulse_alone_each": 0,
    "n_no_stim": 10,
    "iti_min_s": 10.0,
    "iti_max_s": 20.0,
    "randomize": True,
    "seed": None,
}


def _filename(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") + ".json"


def is_builtin(name):
    return name in BUILTINS


def migrate_user_protocols():
    """Move the user's own protocols out of app/protocols (before 1.3.7 they were kept there,
    next to the built-ins) into app/config/protocols, so they're copied with the settings."""
    dest_dir = config.USER_PROTOCOL_DIR
    for p in sorted(config.PROTOCOL_DIR.glob("*.json")):
        data = config.load_json(p, None)
        if not isinstance(data, dict) or data.get("builtin") or data.get("name") in BUILTINS:
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        if dest.exists():
            if config.load_json(dest, None) == data:
                p.unlink()
                continue
            n = 2
            while (dest_dir / f"{p.stem}_{n}.json").exists():
                n += 1
            dest = dest_dir / f"{p.stem}_{n}.json"
        p.replace(dest)


def ensure_builtin():
    migrate_user_protocols()
    # Built-ins are locked and defined here, so keep their files identical to this version.
    for name, proto in BUILTINS.items():
        path = config.PROTOCOL_DIR / _filename(name)
        if config.load_json(path, None) != proto:
            config.save_json(path, proto)
    for old in LEGACY_BUILTIN_NAMES:      # the built-in under its old name
        path = config.PROTOCOL_DIR / _filename(old)
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("builtin"):
                path.unlink()
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    # The default PPI protocol is the user's to edit, so it's kept with their protocols.
    ppi = config.USER_PROTOCOL_DIR / _filename(DEFAULT_PPI["name"])
    if not ppi.exists():
        config.save_json(ppi, DEFAULT_PPI)


def restore_builtin(name):
    config.save_json(config.PROTOCOL_DIR / _filename(name), BUILTINS[name])


def _user_files():
    """(path, protocol) for each of the user's own protocols."""
    out = []
    for p in sorted(config.USER_PROTOCOL_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("name") and data["name"] not in BUILTINS:
            out.append((p, data))
    return out


def list_protocols():
    names = list(BUILTINS)
    for _, data in _user_files():
        if data["name"] not in names:
            names.append(data["name"])
    order = list(BUILTINS)
    names.sort(key=lambda n: (order.index(n) if n in order else len(order), n.lower()))
    return names


def load(name):
    if name in BUILTINS:
        return copy.deepcopy(BUILTINS[name])
    for _, data in _user_files():
        if data["name"] == name:
            data.pop(OLD_NOISE_OFF_KEY, None)    # background noise now always stays on
            return data
    raise KeyError(name)


def save(protocol):
    name = protocol.get("name")
    if is_builtin(name):
        raise ValueError(f"The built-in '{name}' protocol can't be overwritten. Use Save As.")
    path = config.USER_PROTOCOL_DIR / _filename(name)
    # Different names can share a file name ("Hearing Test" / "Hearing_Test"); never replace
    # another protocol's file that way.
    existing = config.load_json(path, {}).get("name") if path.exists() else None
    if existing is not None and existing != name:
        raise ValueError(f"'{name}' can't be saved: its file name is already used by the protocol "
                         f"'{existing}'. Choose a different name.")
    protocol = copy.deepcopy(protocol)
    protocol.pop("builtin", None)
    protocol.pop(OLD_NOISE_OFF_KEY, None)
    config.save_json(path, protocol)


def delete(name):
    if is_builtin(name):
        raise ValueError(f"The built-in '{name}' protocol can't be deleted.")
    for p, data in _user_files():
        if data["name"] == name:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Schedules

def build_schedule(protocol):
    """Return (trials, total_duration_s). Raises ValueError for invalid protocols."""
    if protocol["type"] == "list":
        trials = _list_schedule(protocol)
    elif protocol["type"] == "ppi":
        trials = _ppi_schedule(protocol)
    elif protocol["type"] == "io":
        trials = _io_schedule(protocol)
    else:
        raise ValueError(f"Unknown protocol type: {protocol['type']}")
    if not trials:
        raise ValueError("Protocol has no trials.")
    last = max(_trial_end_s(t) for t in trials)
    return trials, last + float(protocol.get("end_padding_s", 30))


def _trial_end_s(trial):
    end = trial["ref_time_s"]
    for key in ("pulse", "prepulse"):
        s = trial.get(key)
        if s:
            end = max(end, s["onset_s"] + (s["rise_ms"] + s["plateau_ms"] + s["fall_ms"]) / 1000)
    return end


# A white-noise line in a list protocol has no frequency; this one is used only to pick
# out the burst in the microphone recording (as for noise pulses in PPI and I/O).
NOISE_DETECT_HZ = 8000.0


def list_line_stimulus(st, tr):
    """(stimulus, freq_hz) for one line of a list protocol: a tone, or white noise."""
    kind = tr.get("stimulus", st.get("stimulus", "tone"))
    if kind == "noise":
        return "noise", NOISE_DETECT_HZ
    return "tone", float(tr["freq_hz"])


def _list_schedule(p):
    st = p["startle"]
    trials = []
    for i, tr in enumerate(sorted(p["trials"], key=lambda t: t["time_s"]), start=1):
        t = float(tr["time_s"])
        if t < 0:
            raise ValueError("Trial times must be >= 0.")
        kind, freq = list_line_stimulus(st, tr)
        pulse = {"stimulus": kind, "freq_hz": freq,
                 "level_db": float(tr.get("level_db", st["level_db"])),
                 "rise_ms": float(st["rise_ms"]), "plateau_ms": float(st["plateau_ms"]),
                 "fall_ms": float(st["fall_ms"]), "onset_s": t}
        trials.append({"trial": i, "type": "startle", "ref_time_s": t,
                       "pulse": pulse, "prepulse": None, "lead_ms": None})
    return trials


def _ppi_schedule(p):
    bg = p.get("background_noise_db")
    levels = [float(x) for x in p["prepulse"]["levels_above_bg_db"]]
    leads = [float(x) for x in p["lead_intervals_ms"]]
    pp_dur_ms = sum(float(p["prepulse"][k]) for k in ("rise_ms", "plateau_ms", "fall_ms"))
    if bg is None and (levels and (p["n_prepulse_pulse_each"] or p["n_prepulse_alone_each"])):
        raise ValueError("PPI prepulse levels are relative to background noise; set a background level.")
    for lead in leads:
        if lead < pp_dur_ms:
            raise ValueError(f"Lead interval {lead:g} ms is shorter than the prepulse ({pp_dur_ms:g} ms).")
    if float(p["iti_min_s"]) <= 0 or float(p["iti_max_s"]) < float(p["iti_min_s"]):
        raise ValueError("Inter-trial interval: need 0 < min <= max.")

    middle = [("pulse_alone", None, None)] * int(p["n_pulse_alone"])
    for lv in levels:
        for lead in leads:
            middle += [("prepulse_pulse", lv, lead)] * int(p["n_prepulse_pulse_each"])
        middle += [("prepulse_alone", lv, None)] * int(p["n_prepulse_alone_each"])
    middle += [("no_stim", None, None)] * int(p["n_no_stim"])
    rng = random.Random(p.get("seed"))
    if p.get("randomize", True):
        rng.shuffle(middle)
    order = ([("pulse_alone", None, None)] * int(p["start_pulse_alone"]) + middle
             + [("pulse_alone", None, None)] * int(p["end_pulse_alone"]))

    pulse_def = p["pulse"]
    pre_def = p["prepulse"]
    t = float(p["acclimation_s"])
    trials = []
    for i, (kind, lv, lead) in enumerate(order, start=1):
        pulse = prepulse = None
        if kind in ("pulse_alone", "prepulse_pulse"):
            pulse = {k: pulse_def[k] for k in ("stimulus", "freq_hz", "level_db",
                                              "rise_ms", "plateau_ms", "fall_ms")}
            pulse["onset_s"] = t
        if kind in ("prepulse_pulse", "prepulse_alone"):
            prepulse = {k: pre_def[k] for k in ("stimulus", "freq_hz", "rise_ms",
                                               "plateau_ms", "fall_ms")}
            prepulse["level_db"] = float(bg) + lv
            prepulse["level_above_bg_db"] = lv
            prepulse["onset_s"] = t - lead / 1000.0 if kind == "prepulse_pulse" else t
        trials.append({"trial": i, "type": kind, "ref_time_s": t,
                       "pulse": pulse, "prepulse": prepulse, "lead_ms": lead})
        t += rng.uniform(float(p["iti_min_s"]), float(p["iti_max_s"]))
    return trials


def _io_schedule(p):
    levels = [float(x) for x in p["levels_db"]]
    kinds = [("startle", lv) for lv in levels] + ([("no_stim", None)] if p.get("include_no_stim") else [])
    repeats, iti = int(p["repeats"]), float(p["iti_s"])
    if not levels or repeats < 1:
        raise ValueError("I/O needs at least one level and one repeat.")
    if iti <= 0:
        raise ValueError("The interval between trials must be more than 0 s.")
    rng = random.Random(p.get("seed"))
    order = []
    for _ in range(repeats):          # each block has every level once
        block = list(kinds)
        if p.get("randomize", True):
            rng.shuffle(block)
        order += block
    pulse_def = p["pulse"]
    t0 = float(p["acclimation_s"])
    trials = []
    for i, (kind, lv) in enumerate(order, start=1):
        t = t0 + (i - 1) * iti
        pulse = None
        if kind == "startle":
            pulse = {k: pulse_def[k] for k in ("stimulus", "freq_hz", "rise_ms", "plateau_ms", "fall_ms")}
            pulse.update(level_db=lv, onset_s=t)
        trials.append({"trial": i, "type": kind, "ref_time_s": t,
                       "pulse": pulse, "prepulse": None, "lead_ms": None})
    return trials


TRIAL_TYPE_NAMES = {"startle": "startle", "pulse_alone": "pulse alone", "prepulse_pulse": "prepulse + pulse",
                    "prepulse_alone": "prepulse alone", "no_stim": "no stimulus"}


def _sound_name(stim):
    return "noise" if stim["stimulus"] == "noise" else f"{stim['freq_hz'] / 1000:g} kHz"


def trial_sound(tr):
    """What a trial plays, in words, e.g. 'prepulse noise 68 dB, lead 100 ms; pulse 8 kHz 105 dB'."""
    parts = []
    if tr["prepulse"]:
        pp = tr["prepulse"]
        parts.append(f"prepulse {_sound_name(pp)} {pp['level_db']:g} dB"
                     + (f", lead {tr['lead_ms']:g} ms" if tr["lead_ms"] else ""))
    if tr["pulse"]:
        pu = tr["pulse"]
        parts.append(f"{'pulse ' if tr['prepulse'] else ''}{_sound_name(pu)} {pu['level_db']:g} dB")
    return "; ".join(parts) or "(no stimulus)"


def describe_schedule(trials, total_s):
    lines = [f"{len(trials)} trials, session length {total_s:.1f} s ({total_s / 60:.1f} min)", ""]
    lines.append(f"{'#':>3}  {'time (s)':>9}  {'type':<16} stimulus")
    for tr in trials:
        lines.append(f"{tr['trial']:>3}  {tr['ref_time_s']:>9.3f}  "
                     f"{TRIAL_TYPE_NAMES.get(tr['type'], tr['type']):<16} {trial_sound(tr)}")
    return "\n".join(lines)


def levels_text(levels):
    """'70-120 dB, 5 dB steps', '105 dB' or '70, 80, 95 dB'."""
    levels = sorted(set(levels))
    if len(levels) == 1:
        return f"{levels[0]:g} dB"
    steps = {round(b - a, 6) for a, b in zip(levels, levels[1:])}
    if len(steps) == 1 and len(levels) > 2:
        return f"{levels[0]:g}–{levels[-1]:g} dB, {steps.pop():g} dB steps"
    return ", ".join(f"{x:g}" for x in levels) + " dB"


def _seconds_text(values):
    lo, hi = min(values), max(values)
    return f"{lo:g} s" if abs(hi - lo) < 0.001 else f"{lo:.0f}–{hi:.0f} s (varies)"


def summarize(protocol, trials, total_s):
    """The facts about what a protocol will run, as (label, value) pairs for the Protocol tab."""
    out = [("Length", f"{total_s / 60:.1f} min"), ("Trials", str(len(trials)))]
    counts = {}
    for tr in trials:
        counts[tr["type"]] = counts.get(tr["type"], 0) + 1
    if len(counts) > 1:
        order = list(TRIAL_TYPE_NAMES)
        out.append(("Trial types", ", ".join(
            f"{counts[k]} {TRIAL_TYPE_NAMES.get(k, k)}"
            for k in sorted(counts, key=lambda k: order.index(k) if k in order else len(order)))))
    if trials:
        out.append(("First trial", f"{trials[0]['ref_time_s']:g} s"))
    if len(trials) > 1:
        gaps = [b["ref_time_s"] - a["ref_time_s"] for a, b in zip(trials, trials[1:])]
        out.append(("Time between trials", _seconds_text(gaps)))
    pulses = [tr["pulse"] for tr in trials if tr["pulse"]]
    if pulses:
        khz = [f"{f / 1000:g}" for f in sorted({pu["freq_hz"] for pu in pulses if pu["stimulus"] != "noise"})]
        sound = []
        if khz:
            sound.append(", ".join(khz[:-1]) + (" and " if len(khz) > 1 else "") + khz[-1]
                         + (" kHz tones" if len(khz) > 1 else " kHz tone"))
        if any(pu["stimulus"] == "noise" for pu in pulses):
            sound.append("white-noise bursts")
        ms = sum(float(pulses[0][k]) for k in ("rise_ms", "plateau_ms", "fall_ms"))
        out.append(("Startle sound", f"{' and '.join(sound)}, {ms:g} ms"))
        out.append(("Startle levels", levels_text([pu["level_db"] for pu in pulses])))
    pres = [tr for tr in trials if tr["prepulse"]]
    if pres:
        out.append(("Prepulse levels", levels_text([tr["prepulse"]["level_db"] for tr in pres])))
        leads = sorted({tr["lead_ms"] for tr in pres if tr["lead_ms"]})
        if leads:
            out.append(("Lead intervals", ", ".join(f"{x:g}" for x in leads) + " ms"))
    bg = protocol.get("background_noise_db")
    out.append(("Background noise", "off" if bg is None else f"{bg:g} dB, whole session"))
    if protocol.get("assay_variant"):
        out.append(("Assay variant", protocol["assay_variant"]))
    return out


def stimuli_used(protocol):
    """Unique stimulus definitions a protocol plays (for calibration checks)."""
    if protocol["type"] == "io":
        return [dict(protocol["pulse"], level_db=float(lv)) for lv in protocol["levels_db"]]
    if protocol["type"] == "list":
        st = protocol["startle"]
        out = []
        for t in protocol["trials"]:
            kind, freq = list_line_stimulus(st, t)
            out.append(dict(st, stimulus=kind, freq_hz=freq,
                            level_db=float(t.get("level_db", st["level_db"]))))
        return out
    out = [dict(protocol["pulse"])]
    bg = protocol.get("background_noise_db") or 0.0
    for lv in protocol["prepulse"]["levels_above_bg_db"]:
        out.append(dict(protocol["prepulse"], level_db=float(bg) + float(lv), role="prepulse"))
    return out
