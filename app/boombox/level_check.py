"""Can a protocol play every sound at its level with the current speaker calibration?

check() groups a protocol's sounds (one row per tone frequency, white-noise burst,
prepulse and background noise), says how each was calibrated and how close its loudest
level is to the most the speaker can play, and gives one overall verdict. The Calibration
tab shows it in LevelCheckWindow; the session start check uses problem_lines().
"""

import tkinter as tk
from tkinter import ttk

from . import calibration, protocols, sysutil

CAL_WORDS = {"calibrated": "measured", "interpolated": "estimated", "uncalibrated": "not measured"}
OK, WARN, BAD = "ok", "warn", "bad"
FIX_TOO_LOUD = "Turn the amplifier up, then calibrate again."


def _sound_name(stim):
    if stim.get("background"):
        return "Background noise"
    noise = stim.get("stimulus") == "noise"
    if stim.get("role") == "prepulse":
        return "White-noise prepulse" if noise else f"{stim['freq_hz'] / 1000:g} kHz prepulse"
    return "White-noise burst" if noise else f"{stim['freq_hz'] / 1000:g} kHz tone"


def _db(x):
    return f"{round(x, 1):g}"


def check(cal, protocol):
    """Level check for a protocol: {"rows": [...], "verdict", "headline", "advice"}.

    Each row: sound, levels (sorted dB SPL), calibration (measured / estimated / not
    measured), outputs [(level, dBFS)], too_loud (levels beyond what the speaker can play),
    spare_db (room left at the loudest level; negative = too loud), status (ok/warn/bad).
    Levels of a sound that isn't calibrated are unknown, so they're never called too loud.
    """
    stims = protocols.stimuli_used(protocol)
    if protocol.get("background_noise_db") is not None:
        stims.append({"stimulus": "noise", "level_db": float(protocol["background_noise_db"]),
                      "background": True})
    groups = {}
    for s in stims:
        groups.setdefault(_sound_name(s), []).append(s)
    rows = []
    for name, group in groups.items():
        outputs, status_word = [], None
        for level in sorted({float(s["level_db"]) for s in group}):
            dbfs, status, _ = calibration.stimulus_dbfs(cal, group[0], level)
            outputs.append((level, dbfs))
            status_word = CAL_WORDS[status]
        limit = calibration.NOISE_MAX_DBFS if group[0].get("stimulus") == "noise" else calibration.TONE_MAX_DBFS
        known = status_word != "not measured"
        too_loud = [lv for lv, dbfs in outputs if known and dbfs > limit + 1e-9]
        rows.append({
            "sound": name, "levels": [lv for lv, _ in outputs], "calibration": status_word,
            "outputs": outputs, "too_loud": too_loud,
            "spare_db": limit - outputs[-1][1] if known else None,
            "status": BAD if too_loud else (OK if status_word == "measured" else WARN),
        })
    rows.sort(key=lambda r: (r["sound"] == "Background noise", r["sound"]))

    bad = [r for r in rows if r["too_loud"]]
    unmeasured = [r for r in rows if r["calibration"] == "not measured"]
    estimated = [r for r in rows if r["calibration"] == "estimated"]
    name = protocol.get("name", "this protocol")
    if bad:
        n = sum(len(r["too_loud"]) for r in bad)
        verdict = BAD
        headline = f"{n} level{'s are' if n > 1 else ' is'} louder than the speaker can play"
        advice = "; ".join(f"{r['sound']} at {_and([_db(x) for x in r['too_loud']])} dB" for r in bad)
        advice += ". " + FIX_TOO_LOUD
    elif not calibration.is_calibrated(cal):
        verdict, headline = WARN, "Not calibrated"
        advice = "Levels will only be approximate. Calibrate on the Calibration tab first."
    elif unmeasured:
        verdict, headline = WARN, "Some sounds aren't calibrated"
        advice = (f"{_and([r['sound'] for r in unmeasured])}: their levels will only be approximate. "
                  "Measure them on the Calibration tab.")
    else:
        verdict, headline = OK, "Ready"
        advice = f"Every sound in {name} can be played at its level."
        if estimated:
            advice += (f" {_and([r['sound'] for r in estimated])} "
                       f"{'is' if len(estimated) == 1 else 'are'} estimated from the nearest measured "
                       "frequencies; measure it for an exact level.")
    return {"rows": rows, "verdict": verdict, "headline": headline, "advice": advice}


def _and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def spare_text(row):
    if row["spare_db"] is None:
        return "unknown until calibrated"
    loudest = _db(row["levels"][-1])
    if row["spare_db"] < -1e-9:
        return f"{loudest} dB is {_db(-row['spare_db'])} dB too loud"
    return f"{_db(row['spare_db'])} dB to spare"


def problem_lines(cal, protocol):
    """(errors, warnings) for the session start check, one line per sound."""
    result = check(cal, protocol)
    errors, warnings = [], []
    for r in result["rows"]:
        if r["too_loud"]:
            errors.append(f"{r['sound']} at {_and([_db(x) for x in r['too_loud']])} dB is louder than "
                          f"the speaker can play. {FIX_TOO_LOUD}")
        elif calibration.is_calibrated(cal) and r["calibration"] == "not measured":
            warnings.append(f"{r['sound']} isn't calibrated, so its level is only approximate.")
        elif r["calibration"] == "estimated":
            warnings.append(f"{r['sound']} isn't measured; its level is estimated from the nearest "
                            "measured frequencies.")
    return errors, warnings


def calibration_line(cal):
    if not calibration.is_calibrated(cal):
        return "No calibration saved yet."
    parts = []
    if cal.get("date"):
        days = int(calibration.age_days(cal))
        parts.append(f"Calibration from {cal['date'][:10]} ({days} day{'' if days == 1 else 's'} old)")
    else:
        parts.append("Calibration")
    if cal.get("mac_volume") is not None:
        parts.append(f"{sysutil.VOLUME_LABEL} {cal['mac_volume']}")
    measured = []
    if cal.get("noise"):
        measured.append("white noise")
    khz = sorted(float(f) / 1000 for f in cal.get("tones", {}))
    if khz:
        measured.append(", ".join(f"{k:g}" for k in khz) + " kHz")
    if measured:
        parts.append(" and ".join(measured) + " measured")
    return ", ".join(parts)


COLORS = {OK: ("#e6f4ea", "#1e6b34"), WARN: ("#fdf3dc", "#7a4f00"), BAD: ("#fbe9e9", "#a32d2d")}
ICONS = {OK: "✓", WARN: "!", BAD: "✗"}


class LevelCheckWindow:
    def __init__(self, parent, cal, protocol, mono_font="Menlo"):
        result = check(cal, protocol)
        self.top = top = tk.Toplevel(parent)
        top.title(f"Level check: {protocol['name']}")
        top.transient(parent.winfo_toplevel())
        f = ttk.Frame(top, padding=12)
        f.pack(fill="both", expand=True)

        bg, fg = COLORS[result["verdict"]]
        box = tk.Frame(f, bg=bg, padx=10, pady=8)
        box.pack(fill="x")
        bold = ("TkDefaultFont", 13, "bold")
        self.headline = tk.Label(box, text=f"{ICONS[result['verdict']]}  {result['headline']}", bg=bg, fg=fg,
                                 font=bold, anchor="w", justify="left")
        self.headline.pack(fill="x")
        self.advice = tk.Label(box, text=result["advice"], bg=bg, fg=fg, anchor="w", justify="left",
                               wraplength=560)
        self.advice.pack(fill="x")

        ttk.Label(f, text=calibration_line(cal), foreground="#555", wraplength=580,
                  justify="left").pack(anchor="w", pady=(10, 6))

        cols = ("ok", "sound", "levels", "cal", "spare")
        self.table = ttk.Treeview(f, columns=cols, show="headings", height=min(max(len(result["rows"]), 2), 10))
        for c, text, w in (("ok", "", 30), ("sound", "Sound", 160), ("levels", "Levels", 170),
                           ("cal", "Calibration", 100), ("spare", "Loudest level", 200)):
            self.table.heading(c, text=text, anchor="w")
            self.table.column(c, width=w, anchor="center" if c == "ok" else "w", stretch=(c == "spare"))
        for status, (_, color) in COLORS.items():
            self.table.tag_configure(status, foreground=color if status != OK else "")
        for r in result["rows"]:
            self.table.insert("", "end", tags=(r["status"],), values=(
                ICONS[r["status"]], r["sound"], protocols.levels_text(r["levels"]), r["calibration"],
                spare_text(r)))
        self.table.pack(fill="x")

        self.var_detail = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Show output levels (dBFS)", variable=self.var_detail,
                        command=self._toggle_detail).pack(anchor="w", pady=(8, 0))
        lines = []
        for r in result["rows"]:
            lines.append(r["sound"])
            lines += [f"  {_db(lv):>5} dB SPL  ->  {dbfs:6.1f} dBFS" for lv, dbfs in r["outputs"]]
        self.detail = tk.Text(f, height=min(len(lines), 14), width=48, font=(mono_font, 11))
        self.detail.insert("end", "\n".join(lines))
        self.detail.configure(state="disabled")
        self.buttons = ttk.Frame(f)
        self.buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(self.buttons, text="Close", command=top.destroy).pack(side="right")
        top.bind("<Escape>", lambda e: top.destroy())
        self.result = result

    def _toggle_detail(self):
        if self.var_detail.get():
            self.detail.pack(fill="x", pady=(4, 0), before=self.buttons)
        else:
            self.detail.pack_forget()
