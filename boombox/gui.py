"""Tkinter interface for Boom Box."""

import copy
import datetime as dt
import queue
import re
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

import numpy as np
import sounddevice as sd
from PIL import Image, ImageDraw, ImageTk

from . import __version__, audio, calibration, camera, config, protocols, sysutil, uvc
from .config import ADD_NAME_LABEL
from .session import Session
from .stimuli import make_stimulus

IS_WINDOWS = sys.platform == "win32"
UI_FONT = "Segoe UI" if IS_WINDOWS else "Helvetica"
MONO_FONT = "Consolas" if IS_WINDOWS else "Menlo"
VOLUME_LABEL = sysutil.VOLUME_LABEL
NAME_PART_RE = re.compile(r"[A-Za-z0-9-]+")   # arena / camera label rule from the metadata standard
HIGH_TONE_HZ = 12000   # the lab speaker can blow out above 100 dB at these frequencies
PREVIEW_W, PREVIEW_H = 640, 360
PREVIEW_MIN_W = 240
LEFT_MIN_W = 480
SYSTEM_DEFAULT = "System default"
NO_MIC = "None (don't record audio)"


def _wheel_units(event):
    if IS_WINDOWS:
        return -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
    return -int(event.delta) or -1


class ScrollFrame(ttk.Frame):
    """A frame whose content scrolls; scrollbars appear only when content is cut off."""

    def __init__(self, parent, padding=10):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self._update())
        self.canvas.bind("<Configure>", lambda e: self._update())
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self._bind_wheel(True))
            w.bind("<Leave>", lambda e: self._bind_wheel(False))
        self._last = None
        self._poll()

    def _poll(self):
        # Content can change its requested size without any <Configure> event
        # (e.g. the video shrinking), so re-check a few times a second.
        self._update()
        self.after(300, self._poll)

    def _update(self):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        rw, rh = self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()
        if (cw, ch, rw, rh) == self._last:
            return
        self._last = (cw, ch, rw, rh)
        # Stretch content to fill the visible area, but never squash it below its natural size.
        self.canvas.itemconfigure(self._win, width=max(cw, rw), height=max(ch, rh))
        self.canvas.configure(scrollregion=(0, 0, max(cw, rw), max(ch, rh)))
        for bar, needed in ((self.vbar, rh > ch + 1), (self.hbar, rw > cw + 1)):
            if needed:
                bar.grid()
            else:
                bar.grid_remove()

    def _bind_wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
            self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Shift-MouseWheel>")

    def _on_wheel(self, event):
        if isinstance(event.widget, (tk.Text, tk.Listbox)) or self.vbar.winfo_ismapped() == 0:
            return
        self.canvas.yview_scroll(_wheel_units(event), "units")

    def _on_shift_wheel(self, event):
        if self.hbar.winfo_ismapped():
            self.canvas.xview_scroll(_wheel_units(event), "units")


class DialogControls:
    """Lock/re-apply interface (like uvc.UVCCamera) for cameras set through the driver window."""

    def __init__(self, cam):
        self.cam = cam

    def read_all(self):
        return self.cam.read_controls()

    def apply_all(self, values):
        return self.cam.apply_controls(values)


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"Boom Box {__version__}")
        config.ensure_dirs()
        protocols.ensure_builtin()
        self.settings = config.load_settings()
        self.cal = calibration.load()
        self.engine = None
        self.camera = None
        self.uvc = None
        self.session = None
        self.finalize_thread = None
        self.unlocked = False
        self.loaded_protocol = None
        self.cal_playing = None
        self._log_q = queue.Queue()
        self._preview_count = -1
        self._countdown = None
        self.caffeinate = sysutil.keep_awake()

        self._build_ui()
        self.start_audio()
        self.root.after(200, self.start_camera)
        self.root.after(40, self._tick_preview)
        self.root.after(200, self._tick_status)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # =====================================================================
    # Layout
    def _build_ui(self):
        style = ttk.Style()
        style.configure("Big.TButton", font=(UI_FONT, 15, "bold"), padding=8)
        style.configure("Status.TLabel", font=(MONO_FONT, 12))
        style.configure("Header.TLabel", font=(UI_FONT, 13, "bold"))
        style.configure("Stop.TButton", font=(UI_FONT, 15, "bold"), padding=8, foreground="#b00020")

        self.root.minsize(820, 540)
        self.root.geometry("1450x900")
        # Control bar first, packed at the bottom, so it is never squeezed out of the window.
        self._build_control_bar()
        ttk.Separator(self.root).pack(side="bottom", fill="x")

        # Tabs and video side by side with a draggable divider; neither side can collapse.
        paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=10, sashrelief="raised",
                               showhandle=True, handlesize=10, handlepad=60, opaqueresize=True)
        paned.pack(side="top", fill="both", expand=True, padx=4, pady=4)
        left = ttk.Frame(paned)
        right = ScrollFrame(paned, padding=4)
        paned.add(left, minsize=LEFT_MIN_W, stretch="always")
        paned.add(right, minsize=PREVIEW_MIN_W + 30, stretch="always")
        self.paned = paned
        # Keep the video panel at a fixed share of the window (the share changes when the
        # divider is dragged), so shrinking the window shrinks both sides.
        self._right_frac = 0.25     # video panel starts at a quarter of the window width
        paned.bind("<ButtonRelease-1>", self._on_sash_moved, add="+")
        paned.bind("<Configure>", self._on_paned_resize, add="+")

        nb = ttk.Notebook(left)
        nb.pack(fill="both", expand=True)
        tabs = {}
        for key, name in (("session", "Session"), ("protocol", "Protocol"), ("cal", "Calibration"),
                          ("camera", "Camera"), ("settings", "Settings")):
            sf = ScrollFrame(nb)
            nb.add(sf, text=name)
            tabs[key] = sf.inner
        self.tab_session, self.tab_protocol = tabs["session"], tabs["protocol"]
        self.tab_cal, self.tab_camera, self.tab_settings = tabs["cal"], tabs["camera"], tabs["settings"]
        self.notebook = nb

        self._build_preview(right.inner)
        self.preview_pane = right
        self._build_session_tab()
        self._build_protocol_tab()
        self._build_calibration_tab()
        self._build_camera_tab()
        self._build_settings_tab()

    def _build_control_bar(self):
        bar = ttk.Frame(self.root, padding=(10, 6))
        bar.pack(side="bottom", fill="x")
        self.btn_start = ttk.Button(bar, text="START SESSION", style="Big.TButton", command=self.on_start)
        self.btn_start.pack(side="left", padx=(0, 4))
        self.btn_stop = ttk.Button(bar, text="STOP", style="Stop.TButton", command=self.on_stop)
        self.btn_stop.pack(side="left", padx=4)
        self.btn_next = ttk.Button(bar, text="Next animal", style="Big.TButton",
                                   command=self.on_next_animal, state="disabled")
        self.btn_next.pack(side="left", padx=4)
        self.btn_noise = ttk.Button(bar, text="Start background noise", command=self.toggle_noise)
        self.btn_noise.pack(side="left", padx=(12, 4))
        self.big_status = tk.StringVar(value="Starting...")
        tk.Label(bar, textvariable=self.big_status, font=(UI_FONT, 18, "bold"),
                 fg="#b00020", anchor="e").pack(side="right", fill="x", expand=True)
        self.root.bind_all("<Escape>", lambda e: self.on_stop())

    def _build_preview(self, parent):
        self._photo = ImageTk.PhotoImage(Image.new("RGB", (PREVIEW_W, PREVIEW_H)))
        self.preview = tk.Label(parent, bg="black", image=self._photo)
        self.preview.pack(anchor="n")
        self.preview_box = (PREVIEW_W, PREVIEW_H)
        parent.master.bind("<Configure>", self._on_preview_resize, add="+")
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        self.status_vars = {}
        self.status_value_labels = []
        for i, key in enumerate(["Camera", "Video", "Recording", "Elapsed", "Next stimulus", "Trial",
                                 "Dropped frames", "Microphone", "Background noise", VOLUME_LABEL]):
            ttk.Label(grid, text=key + ":", style="Status.TLabel").grid(row=i, column=0, sticky="w")
            v = tk.StringVar(value="-")
            lab = ttk.Label(grid, textvariable=v, style="Status.TLabel", wraplength=400)
            lab.grid(row=i, column=1, sticky="w")
            self.status_value_labels.append(lab)
            self.status_vars[key] = v

    def _on_paned_resize(self, event):
        # React to the panels' own resize (not the window's), so the width is already current.
        if event.widget is self.paned:
            self.root.after_idle(lambda w=event.width: self._place_sash(w))

    def _place_sash(self, width=None):
        width = width or self.paned.winfo_width()
        if width < 50:
            return
        right = width * self._right_frac
        right = min(max(right, PREVIEW_MIN_W + 30), PREVIEW_W * 2, max(PREVIEW_MIN_W + 30, width - LEFT_MIN_W))
        x = int(width - right)
        if abs(self.paned.sash_coord(0)[0] - x) > 2:
            self.paned.sash_place(0, x, 1)

    def _on_sash_moved(self, event):
        width = self.paned.winfo_width()
        if width > 50:
            self._right_frac = (width - self.paned.sash_coord(0)[0]) / width

    def _on_preview_resize(self, event):
        """Fit the video to the right-hand panel, leaving room for the status lines below it."""
        w = max(PREVIEW_MIN_W, event.width - 36)   # room for padding, border and a scrollbar
        room_h = event.height - 260
        if room_h >= PREVIEW_MIN_W * 9 // 16:
            w = min(w, int(room_h * 16 / 9))
        w = max(PREVIEW_MIN_W, min(w, 1280))
        for lab in self.status_value_labels:
            lab.configure(wraplength=max(100, event.width - 200))
        if (w, w * 9 // 16) != self.preview_box:
            self.preview_box = (w, w * 9 // 16)
            self._preview_count = -1

    # ---------------------------------------------------------------------
    def _build_session_tab(self):
        f = self.tab_session
        ttk.Label(f, text="Experimenter", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        self.var_experimenter = tk.StringVar(value=self.settings.get("last_experimenter", ""))
        self.cb_experimenter = ttk.Combobox(f, textvariable=self.var_experimenter, state="readonly",
                                            width=24)
        self.cb_experimenter.grid(row=0, column=1, sticky="w", pady=2)
        self.cb_experimenter.bind("<<ComboboxSelected>>", self.on_experimenter)
        self._refresh_experimenters()

        self.animal_vars = {}
        # Field names follow the Track Tamer metadata standard (they go into _info.json).
        fields = [("animal_id", "Animal ID *"), ("sex", "Sex (F / M / U)"), ("strain", "Strain"),
                  ("dob", "Date of birth (YYYY-MM-DD)"), ("cohort", "Cohort / litter"),
                  ("treatment", "Treatment"), ("trial_day", "Trial day (1, 2, ...)"),
                  ("session_number", "Session number that day"), ("notes", "Notes")]
        for i, (key, label) in enumerate(fields, start=1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w")
            v = tk.StringVar(value="U" if key == "sex" else "")
            if key == "sex":
                w = ttk.Combobox(f, textvariable=v, values=["F", "M", "U"], state="readonly", width=6)
            else:
                w = ttk.Entry(f, textvariable=v, width=12 if key == "notes" else
                              (8 if key in ("trial_day", "session_number") else 26))
            # Notes stretches with the pane (and shrinks back) instead of forcing a scrollbar.
            w.grid(row=i, column=1, sticky="ew" if key == "notes" else "w", pady=2)
            self.animal_vars[key] = v
            if key == "animal_id":
                self.entry_animal = w

        r = len(fields) + 1
        ttk.Label(f, text="Protocol", style="Header.TLabel").grid(row=r, column=0, sticky="w", pady=(10, 2))
        self.var_protocol = tk.StringVar()
        self.cb_protocol = ttk.Combobox(f, textvariable=self.var_protocol, state="readonly", width=24)
        self.cb_protocol.grid(row=r, column=1, sticky="w", pady=(10, 2))
        self.cb_protocol.bind("<<ComboboxSelected>>", lambda e: self.on_protocol_selected())

        r += 1
        ttk.Label(f, text="Save data in").grid(row=r, column=0, sticky="w")
        df = ttk.Frame(f)
        df.grid(row=r, column=1, sticky="ew")
        self.var_data_dir = tk.StringVar(value=self.settings["data_dir"])
        ttk.Button(df, text="Change...", command=self.choose_data_dir).pack(side="right")
        self.lbl_data_dir = ttk.Label(df, textvariable=self.var_data_dir, wraplength=120)
        self.lbl_data_dir.pack(side="left", fill="x", expand=True)
        # Wrap the folder path to the visible tab width (not the row's own width, which
        # would never let it shrink back).
        f.master.bind("<Configure>", lambda e: self.lbl_data_dir.configure(
            wraplength=max(120, e.width - 230)), add="+")

        r += 1
        ttk.Label(f, text="Log", style="Header.TLabel").grid(row=r, column=0, sticky="w", pady=(12, 2))
        r += 1
        # Small requested width so the log shrinks with the pane; it wraps long lines.
        self.log_text = ScrolledText(f, height=14, width=20, font=(MONO_FONT, 11), state="disabled",
                                     wrap="word")
        self.log_text.grid(row=r, column=0, columnspan=2, sticky="nsew")
        f.rowconfigure(r, weight=1)
        f.columnconfigure(1, weight=1)

    # ---------------------------------------------------------------------
    def _build_protocol_tab(self):
        f = self.tab_protocol
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Protocol:").pack(side="left")
        self.cb_protocol_edit = ttk.Combobox(top, textvariable=self.var_protocol, state="readonly",
                                             width=28)
        self.cb_protocol_edit.pack(side="left", padx=4)
        self.cb_protocol_edit.bind("<<ComboboxSelected>>", lambda e: self.on_protocol_selected())
        for text, cmd in (("New list", self.new_list_protocol), ("New PPI", self.new_ppi_protocol),
                          ("Save", self.save_protocol), ("Save As...", self.save_protocol_as),
                          ("Delete", self.delete_protocol)):
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=2)

        lockrow = ttk.Frame(f)
        lockrow.pack(fill="x", pady=6)
        self.var_lock = tk.StringVar()
        ttk.Label(lockrow, textvariable=self.var_lock, foreground="#b00020").pack(side="left")
        self.btn_unlock = ttk.Button(lockrow, text="Unlock for editing", command=self.unlock_protocol)
        self.btn_unlock.pack(side="left", padx=6)
        self.btn_restore = ttk.Button(lockrow, text="Restore original",
                                      command=self.restore_builtin)
        self.btn_restore.pack(side="left", padx=6)

        self.editor = ttk.Frame(f)
        self.editor.pack(fill="x")
        prow = ttk.Frame(f)
        prow.pack(fill="x", pady=4)
        ttk.Button(prow, text="Preview schedule", command=self.preview_schedule).pack(side="left")
        self.schedule_text = ScrolledText(f, height=14, width=90, font=(MONO_FONT, 11))
        self.schedule_text.pack(fill="both", expand=True)
        self.refresh_protocol_list(self.settings.get("last_protocol"))

    # ---------------------------------------------------------------------
    def _build_calibration_tab(self):
        f = self.tab_cal
        msg = ("1. Put the sound level meter where the mouse's head will be.  2. For each row, press "
               "Play (continuous tone), read the meter, and type the reading into 'Measured dB SPL'.  "
               "3. Press Save calibration.  Start at a low test level; wear hearing protection.  "
               f"Leave the {VOLUME_LABEL} at the same setting for every session after calibrating.")
        ttk.Label(f, text=msg, wraplength=760, justify="left").pack(anchor="w")
        info = ttk.Frame(f)
        info.pack(fill="x", pady=6)
        ttk.Label(info, text="Meter weighting:").pack(side="left")
        self.var_weighting = tk.StringVar(value=self.cal.get("weighting") or "Z")
        ttk.Combobox(info, textvariable=self.var_weighting, values=["Z (flat)", "C", "A"],
                     width=9, state="readonly").pack(side="left", padx=4)
        self.var_cal_status = tk.StringVar()
        ttk.Label(info, textvariable=self.var_cal_status).pack(side="left", padx=12)

        self.cal_table = ttk.Frame(f)
        self.cal_table.pack(fill="x", pady=4)
        add = ttk.Frame(f)
        add.pack(fill="x", pady=4)
        ttk.Label(add, text="Add frequency (kHz):").pack(side="left")
        self.var_add_freq = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_add_freq, width=8).pack(side="left", padx=4)
        ttk.Button(add, text="Add", command=self.add_cal_freq).pack(side="left")
        ttk.Button(add, text="Stop all sound", command=self.stop_cal_sound).pack(side="left", padx=20)
        actions = ttk.Frame(f)
        actions.pack(fill="x", pady=(4, 8))
        ttk.Button(actions, text="Check selected protocol", command=self.check_protocol_levels).pack(side="left")
        ttk.Button(actions, text="Save calibration", style="Big.TButton",
                   command=self.save_calibration).pack(side="left", padx=12)
        self.cal_freqs = sorted({int(float(k)) for k in self.cal.get("tones", {})}
                                | set(calibration.DEFAULT_FREQS_HZ))
        self.cal_rows = {}
        self.build_cal_table()

    def build_cal_table(self):
        for w in self.cal_table.winfo_children():
            w.destroy()
        heads = ["Stimulus", "Test level (dBFS)", "", "", "Measured dB SPL",
                 "dB SPL at 0 dBFS", "Loudest possible"]
        for c, h in enumerate(heads):
            ttk.Label(self.cal_table, text=h, style="Header.TLabel").grid(row=0, column=c, padx=6, sticky="w")
        old = {k: (r["test"].get(), r["meas"].get()) for k, r in self.cal_rows.items()}
        self.cal_rows = {}
        keys = ["noise"] + self.cal_freqs
        for i, key in enumerate(keys, start=1):
            entry = self.cal.get("noise") if key == "noise" else self.cal.get("tones", {}).get(str(key))
            default_test = -40.0 if key == "noise" else -30.0
            test = tk.StringVar(value=str(entry["test_dbfs"] if entry else default_test))
            meas = tk.StringVar(value=str(entry["measured_db"]) if entry else "")
            if key in old:
                test.set(old[key][0])
                meas.set(old[key][1])
            label = "White noise (RMS)" if key == "noise" else f"{key / 1000:g} kHz tone"
            cell = ttk.Frame(self.cal_table)
            cell.grid(row=i, column=0, sticky="w", padx=6, pady=2)
            ttk.Label(cell, text=label).pack(anchor="w")
            if key != "noise" and key >= HIGH_TONE_HZ:
                # Directly under the tone's name so it can't be missed.
                ttk.Label(cell, text="⚠ Max 100 dB: speaker can blow out",
                          foreground="#b00020").pack(anchor="w")
            ttk.Entry(self.cal_table, textvariable=test, width=8).grid(row=i, column=1, padx=6)
            btn = ttk.Button(self.cal_table, text="Play", width=6,
                             command=lambda k=key: self.toggle_cal_play(k))
            btn.grid(row=i, column=2)
            if key != "noise":
                ttk.Button(self.cal_table, text="10 ms burst", width=10,
                           command=lambda k=key: self.play_cal_burst(k)).grid(row=i, column=3)
            ttk.Entry(self.cal_table, textvariable=meas, width=8).grid(row=i, column=4, padx=6)
            ref = tk.StringVar()
            mx = tk.StringVar()
            ttk.Label(self.cal_table, textvariable=ref).grid(row=i, column=5, padx=6, sticky="w")
            ttk.Label(self.cal_table, textvariable=mx).grid(row=i, column=6, padx=6, sticky="w")
            self.cal_rows[key] = {"test": test, "meas": meas, "btn": btn, "ref": ref, "max": mx}
            meas.trace_add("write", lambda *a: self.update_cal_labels())
            test.trace_add("write", lambda *a: self.update_cal_labels())
        self.update_cal_labels()

    # ---------------------------------------------------------------------
    def _build_camera_tab(self):
        f = self.tab_camera
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="Camera:").pack(side="left")
        self.var_camera = tk.StringVar(value=self.settings.get("camera_name", ""))
        self.cb_camera = ttk.Combobox(row, textvariable=self.var_camera, state="readonly", width=30)
        self.cb_camera.pack(side="left", padx=4)
        ttk.Button(row, text="Refresh list", command=self.refresh_cameras).pack(side="left")

        row2 = ttk.Frame(f)
        row2.pack(fill="x", pady=6)
        ttk.Label(row2, text="Resolution:").pack(side="left")
        res_label = next((k for k, v in camera.RESOLUTIONS.items() if v == self.settings["resolution"]),
                         list(camera.RESOLUTIONS)[1])
        self.var_resolution = tk.StringVar(value=res_label)
        ttk.Combobox(row2, textvariable=self.var_resolution, values=list(camera.RESOLUTIONS),
                     state="readonly", width=24).pack(side="left", padx=4)
        ttk.Label(row2, text="Frame rate:").pack(side="left", padx=(12, 0))
        self.var_fps = tk.StringVar(value=str(self.settings["fps"]))
        ttk.Combobox(row2, textvariable=self.var_fps, values=[str(x) for x in camera.FPS_CHOICES],
                     state="readonly", width=5).pack(side="left", padx=4)
        ttk.Label(row2, text="Camera latency (ms):").pack(side="left", padx=(12, 0))
        self.var_latency = tk.StringVar(value=str(self.settings["camera_latency_ms"]))
        ttk.Entry(row2, textvariable=self.var_latency, width=6).pack(side="left", padx=4)

        row3 = ttk.Frame(f)
        row3.pack(fill="x")
        ttk.Button(row3, text="Apply / restart camera", command=self.apply_camera).pack(side="left")
        ttk.Button(row3, text="Show camera modes", command=self.show_modes).pack(side="left", padx=6)

        ttk.Separator(f).pack(fill="x", pady=10)
        lockrow = ttk.Frame(f)
        lockrow.pack(fill="x")
        self.var_cam_lock = tk.BooleanVar(value=self.settings.get("camera_controls_locked", False))
        ttk.Checkbutton(lockrow, text="Lock camera settings (saved and re-applied every session)",
                        variable=self.var_cam_lock, command=self.on_cam_lock).pack(side="left")
        ttk.Button(lockrow, text="Reset to camera defaults", command=self.reset_cam_controls).pack(side="right")
        self.var_uvc_status = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.var_uvc_status, wraplength=760).pack(anchor="w", pady=4)
        ttk.Label(f, text="Tip: turn auto exposure off before setting exposure and gain. Keep exposure "
                          "shorter than one frame (33 ms at 30 fps, 11 ms at 90 fps) or the frame rate drops.",
                  wraplength=760, foreground="#555").pack(anchor="w")
        self.controls_frame = ttk.Frame(f)
        self.controls_frame.pack(fill="x", pady=6)
        self.control_vars = {}
        self.control_widgets = []
        self.refresh_cameras(initial=True)

    # ---------------------------------------------------------------------
    def _build_settings_tab(self):
        f = self.tab_settings
        r = 0

        def row(label, widget):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="w", pady=3)
            r += 1

        ttk.Label(f, text="Audio", style="Header.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        self.var_out_dev = tk.StringVar(value=self.settings["output_device"] or SYSTEM_DEFAULT)
        row("Sound output (to amplifier)",
            ttk.Combobox(f, textvariable=self.var_out_dev, state="readonly", width=34,
                         values=[SYSTEM_DEFAULT] + audio.list_output_devices()))
        self.var_channel = tk.StringVar(value=self.settings["channel_mode"])
        row("Output channel", ttk.Combobox(f, textvariable=self.var_channel, state="readonly", width=10,
                                           values=["both", "left", "right"]))
        self.var_rate = tk.StringVar(value=str(self.settings["sample_rate"]))
        row("Sample rate (Hz)", ttk.Combobox(f, textvariable=self.var_rate, state="readonly", width=10,
                                             values=["44100", "48000", "96000"]))
        self.var_mic = tk.StringVar(value=self.settings["mic_device"] or NO_MIC)
        microw = ttk.Frame(f)
        ttk.Combobox(microw, textvariable=self.var_mic, state="readonly", width=34,
                     values=[NO_MIC] + audio.list_input_devices()).pack(side="left")
        ttk.Button(microw, text="Test mic (2 s)", command=self.test_mic).pack(side="left", padx=6)
        row("Microphone (sync check)", microw)
        self.var_keep_noise = tk.BooleanVar(value=self.settings["keep_noise_after_session"])
        row("", ttk.Checkbutton(f, text="Keep background noise on after a session ends",
                                variable=self.var_keep_noise))

        ttk.Label(f, text="This rig (used in file names and the info file)", style="Header.TLabel").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(12, 0)); r += 1
        self.var_arena = tk.StringVar(value=self.settings["arena"])
        row("Arena (letters, digits, - only)", ttk.Entry(f, textvariable=self.var_arena, width=12))
        self.var_room = tk.StringVar(value=self.settings["room"])
        row("Room", ttk.Entry(f, textvariable=self.var_room, width=20))
        self.var_camera_label = tk.StringVar(value=self.settings["camera_label"])
        row("Camera label (letters, digits, - only)", ttk.Entry(f, textvariable=self.var_camera_label, width=12))

        ttk.Label(f, text="Session", style="Header.TLabel").grid(row=r, column=0, sticky="w", pady=(12, 0)); r += 1
        self.var_countdown = tk.StringVar(value=str(self.settings["countdown_s"]))
        row("Countdown before start (s)", ttk.Entry(f, textvariable=self.var_countdown, width=6))
        self.var_cal_age = tk.StringVar(value=str(self.settings["calibration_max_age_days"]))
        row("Warn if calibration older than (days)", ttk.Entry(f, textvariable=self.var_cal_age, width=6))

        ttk.Label(f, text="Video file", style="Header.TLabel").grid(row=r, column=0, sticky="w", pady=(12, 0)); r += 1
        self.var_crf = tk.StringVar(value=str(self.settings["video_crf"]))
        row("Quality (CRF, lower = better/larger, 18 is visually lossless)",
            ttk.Entry(f, textvariable=self.var_crf, width=6))
        self.var_preset = tk.StringVar(value=self.settings["video_preset"])
        row("Encoder speed", ttk.Combobox(f, textvariable=self.var_preset, state="readonly", width=10,
                                          values=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"]))

        ttk.Button(f, text="Save settings and restart audio", command=self.apply_settings).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=14)

    # =====================================================================
    # Logging / helpers
    def log(self, msg):
        self._log_q.put(f"{dt.datetime.now():%H:%M:%S}  {msg}")

    def _drain_log(self):
        lines = []
        while not self._log_q.empty():
            lines.append(self._log_q.get())
        if lines:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "\n".join(lines) + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def save_settings(self):
        config.save_settings(self.settings)

    def recording(self):
        return self.session is not None and self.session.state == "recording"

    def busy(self):
        return self.session is not None and self.session.state in ("recording", "finalizing") \
            or self._countdown is not None

    # =====================================================================
    # Audio
    def start_audio(self):
        if self.engine:
            noise = self.engine.noise_target
            self.engine.stop()
        else:
            noise = 0.0
        try:
            self.engine = audio.AudioEngine(self.settings["output_device"], self.settings["sample_rate"],
                                            self.settings["channel_mode"])
            self.engine.start()
            self.engine.noise_target = noise
            self.log(f"Audio output: {self.engine.actual_device}, {self.engine.fs} Hz, "
                     f"channel {self.settings['channel_mode']}")
            if not IS_WINDOWS and "headphone" not in self.engine.actual_device.lower():
                self.log("NOTE: sound output is not 'External Headphones'. Plug the amplifier into the "
                         "headphone jack and choose it under Settings if needed.")
        except Exception as e:
            self.engine = None
            messagebox.showerror("Audio", f"Could not open the sound output:\n{e}")

    def selected_protocol(self):
        try:
            return protocols.load(self.var_protocol.get())
        except KeyError:
            return None

    def toggle_noise(self):
        if not self.engine:
            return
        if self.engine.noise_target > 0:
            if self.recording():
                if not messagebox.askyesno("Background noise", "Turn off background noise during the session?"):
                    return
            self.engine.set_noise_dbfs(None)
            self.log("Background noise off.")
            if self.session:
                self.session.log("Background noise turned off by user.")
            return
        p = self.selected_protocol()
        if not p or p.get("background_noise_db") is None:
            messagebox.showinfo("Background noise", "The selected protocol has no background noise level.")
            return
        db = p["background_noise_db"]
        dbfs, status, ok = calibration.stimulus_dbfs(self.cal, {"stimulus": "noise"}, db)
        if not ok:
            messagebox.showerror("Background noise", f"{db} dB SPL needs {dbfs:.1f} dBFS, which would clip. "
                                                     "Turn up the amplifier and recalibrate.")
            return
        self.engine.set_noise_dbfs(dbfs)
        self.log(f"Background noise on: {db:g} dB SPL ({dbfs:.1f} dBFS, {status}).")

    def test_mic(self):
        name = self.var_mic.get()
        if name == NO_MIC:
            messagebox.showinfo("Microphone", "Choose a microphone first.")
            return
        try:
            idx = audio._device_index(name, "input")
            fs = int(sd.query_devices(idx)["default_samplerate"])
            data = sd.rec(int(2 * fs), samplerate=fs, channels=1, device=idx, blocking=True)
            peak = 20 * np.log10(max(float(np.abs(data).max()), 1e-6))
            rms = 20 * np.log10(max(float(np.sqrt(np.mean(data ** 2))), 1e-6))
            messagebox.showinfo("Microphone", f"{name}\nPeak {peak:.1f} dBFS, average {rms:.1f} dBFS\n\n"
                                "If both are below -80 dBFS, check microphone permission: "
                                + ("Settings > Privacy & security > Microphone > Let desktop apps "
                                   "access your microphone." if IS_WINDOWS else
                                   "System Settings > Privacy & Security > Microphone > Terminal."))
        except Exception as e:
            messagebox.showerror("Microphone", str(e))

    # =====================================================================
    # Camera
    def refresh_cameras(self, initial=False):
        try:
            names = camera.list_cameras()
        except Exception as e:
            names = []
            self.log(f"Could not list cameras: {e}")
        self.cb_camera["values"] = names + [camera.TEST_PATTERN]
        cur = self.var_camera.get()
        if cur not in names + [camera.TEST_PATTERN]:
            self.var_camera.set(camera.default_camera(names))

    def camera_params(self):
        w, h = camera.RESOLUTIONS[self.var_resolution.get()].split("x")
        return self.var_camera.get(), int(w), int(h), int(self.var_fps.get()), float(self.var_latency.get() or 0)

    def apply_camera(self):
        if self.busy():
            messagebox.showwarning("Camera", "Can't change the camera during a session.")
            return
        try:
            name, w, h, fps, lat = self.camera_params()
        except ValueError:
            messagebox.showerror("Camera", "Camera latency must be a number.")
            return
        self.settings.update(camera_name=name, resolution=f"{w}x{h}", fps=fps, camera_latency_ms=lat)
        self.save_settings()
        self.start_camera()

    def start_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera = None
        name, w, h, fps, lat = self.camera_params()
        try:
            cam = camera.make_camera(name, w, h, fps, lat)
            cam.start()
            self.camera = cam
            self._preview_count = -1
            self.log(f"Camera: {name}, {w}x{h} @ {fps} fps")
        except Exception as e:
            self.log(f"CAMERA: {e}")
            messagebox.showerror("Camera", str(e))
        self.connect_uvc()
        self.root.after(4000, self._check_camera_started)

    def _check_camera_started(self):
        cam = self.camera
        if cam is None:
            return
        if cam.frame_count == 0:
            detail = cam.error or cam.stderr_text() or "no frames received"
            self.log(f"CAMERA not delivering frames: {detail}")
            if IS_WINDOWS:
                hint = ("Close other programs that may be using the camera (Camera app, Zoom, Teams), and "
                        "check Settings > Privacy & security > Camera > Let desktop apps access your camera.")
            else:
                hint = ("If this is the first run, allow camera access for Terminal in System "
                        "Settings > Privacy & Security > Camera, then quit and restart the program.")
            messagebox.showerror("Camera", f"The camera is not sending video.\n\n{hint}\n\n"
                                 f"Details: {detail[-600:]}")
        else:
            fps = cam.measured_fps()
            if fps and abs(fps - cam.fps) / cam.fps > 0.05:
                self.log(f"WARNING: camera is running at {fps:.1f} fps, not {cam.fps}. "
                         "Lower the exposure or add light.")

    def show_modes(self):
        name = self.var_camera.get()
        try:
            modes = camera.list_modes(name)
        except Exception as e:
            messagebox.showerror("Camera modes", str(e))
            return
        lines = sorted({f"{w}x{h} @ {f:.2f} fps" for w, h, f in modes},
                       key=lambda s: (int(s.split("x")[0]), int(s.split("x")[1].split()[0]), float(s.split("@")[1].split()[0])))
        win = tk.Toplevel(self.root)
        win.title(f"Modes: {name}")
        t = ScrolledText(win, width=40, height=30, font=(MONO_FONT, 11))
        t.pack(fill="both", expand=True)
        t.insert("end", "\n".join(lines) or "No modes reported")

    def connect_uvc(self):
        self.uvc = None
        for w in self.controls_frame.winfo_children():
            w.destroy()
        self.control_vars, self.control_widgets = {}, []
        if getattr(self.camera, "has_settings_dialog", False):
            self.build_dialog_controls()
            return
        name = self.var_camera.get()
        ids = camera.usb_cameras().get(name)
        if not ids:
            self.var_uvc_status.set("Camera controls: not available for this camera.")
            return
        try:
            self.uvc = uvc.UVCCamera(*ids)
        except Exception as e:
            self.var_uvc_status.set(f"Camera controls unavailable: {e}")
            return
        if self.var_cam_lock.get() and self.settings.get("camera_controls"):
            errs = self.uvc.apply_all(self.settings["camera_controls"])
            self.log("Applied locked camera settings." + (f" Errors: {errs}" if errs else ""))
        self.build_controls()

    def build_controls(self):
        vals = self.uvc.read_all()
        r = 0
        for name in uvc.APPLY_ORDER:
            if name not in self.uvc.info:
                continue
            _, _, _, _, kind, label = uvc.CONTROLS[name]
            info = self.uvc.info[name]
            ttk.Label(self.controls_frame, text=label).grid(row=r, column=0, sticky="w", pady=1)
            if kind in ("bool", "ae"):
                v = tk.BooleanVar(value=bool(vals.get(name)))
                w = ttk.Checkbutton(self.controls_frame, variable=v,
                                    command=lambda n=name, v=v: self.set_control(n, v.get()))
                w.grid(row=r, column=1, sticky="w")
            elif kind == "menu":
                v = tk.StringVar(value=uvc.POWER_LINE.get(vals.get(name), "Off"))
                w = ttk.Combobox(self.controls_frame, textvariable=v, values=list(uvc.POWER_LINE.values()),
                                 state="readonly", width=12)
                w.bind("<<ComboboxSelected>>", lambda e, n=name, v=v: self.set_control(
                    n, {s: k for k, s in uvc.POWER_LINE.items()}[v.get()]))
                w.grid(row=r, column=1, sticky="w")
            else:
                v = tk.IntVar(value=int(vals.get(name, info.get("def", 0))))
                fr = ttk.Frame(self.controls_frame)
                fr.grid(row=r, column=1, sticky="w")
                w = ttk.Scale(fr, from_=info["min"], to=info["max"], length=320,
                              command=lambda s, n=name, v=v: self._on_scale(n, v, s))
                w.set(v.get())
                w.pack(side="left")
                ttk.Label(fr, textvariable=v, width=6).pack(side="left", padx=4)
            self.control_vars[name] = v
            self.control_widgets.append(w)
            r += 1
        self.update_lock_state()
        self.var_uvc_status.set("Camera controls connected." + ("  LOCKED." if self.var_cam_lock.get() else ""))

    def _on_scale(self, name, var, s):
        val = int(round(float(s)))
        if var.get() != val:
            var.set(val)
            self.set_control(name, val)

    def set_control(self, name, value):
        if not self.uvc or self.var_cam_lock.get():
            return
        try:
            self.uvc.set(name, value)
        except Exception as e:
            self.var_uvc_status.set(f"Could not set {name}: {e}")

    def on_cam_lock(self):
        locked = self.var_cam_lock.get()
        if locked and self.uvc:
            self.settings["camera_controls"] = self.uvc.read_all()
            self.log(f"Camera settings locked: {self.settings['camera_controls']}")
        self.settings["camera_controls_locked"] = locked
        self.save_settings()
        self.update_lock_state()
        if self.uvc:
            self.var_uvc_status.set("Camera controls connected." + ("  LOCKED." if locked else ""))

    def update_lock_state(self):
        state = "disabled" if self.var_cam_lock.get() else "normal"
        for w in self.control_widgets:
            try:
                w.configure(state=state if not isinstance(w, ttk.Combobox) else
                            ("disabled" if state == "disabled" else "readonly"))
            except tk.TclError:
                pass

    def build_dialog_controls(self):
        """Windows: camera settings are changed in the driver's own window, then locked here."""
        self.uvc = DialogControls(self.camera)
        f = self.controls_frame
        btn = ttk.Button(f, text="Open camera settings window", command=self.open_camera_dialog)
        btn.grid(row=0, column=0, sticky="w", pady=4)
        ttk.Button(f, text="Show current values", command=self.show_camera_values).grid(
            row=0, column=1, sticky="w", padx=8)
        ttk.Label(f, wraplength=520, justify="left", text=(
            "Use the camera's settings window to turn off automatic exposure and set exposure, gain and "
            "focus while watching the preview. Then tick 'Lock camera settings' above: the values are "
            "saved and re-applied every session.")).grid(row=1, column=0, columnspan=2, sticky="w")
        self.var_cam_values = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.var_cam_values, font=(MONO_FONT, 11), justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=4)
        self.control_widgets = [btn]
        self.update_lock_state()
        self.var_uvc_status.set("Camera controls: camera settings window." +
                                ("  LOCKED." if self.var_cam_lock.get() else ""))
        if self.var_cam_lock.get() and self.settings.get("camera_controls"):
            self._apply_locked_when_ready(time.time() + 15)

    def _apply_locked_when_ready(self, deadline):
        """Re-apply locked values once the camera has opened (it opens in the background)."""
        cam = self.camera
        if cam is None or not getattr(cam, "has_settings_dialog", False):
            return
        if cam.frame_count == 0:
            if time.time() < deadline and not cam.error:
                self.root.after(500, lambda: self._apply_locked_when_ready(deadline))
            return
        try:
            errs = self.uvc.apply_all(self.settings["camera_controls"])
            self.log("Applied locked camera settings." + (f" Not accepted: {errs}" if errs else ""))
        except Exception as e:
            self.log(f"Could not apply locked camera settings: {e}")

    def open_camera_dialog(self):
        if self.var_cam_lock.get():
            messagebox.showinfo("Camera", "Unlock camera settings first.")
            return
        try:
            self.camera.open_settings_dialog()
        except Exception as e:
            messagebox.showerror("Camera", f"Could not open the camera settings window: {e}")

    def show_camera_values(self):
        try:
            vals = self.uvc.read_all()
            self.var_cam_values.set("\n".join(f"{k:<14} {v:g}" for k, v in vals.items()) or "(none reported)")
        except Exception as e:
            self.var_cam_values.set(f"Could not read values: {e}")

    def reset_cam_controls(self):
        if isinstance(self.uvc, DialogControls):
            messagebox.showinfo("Camera", "Use the Default button in the camera settings window.")
            return
        if not self.uvc or self.var_cam_lock.get():
            messagebox.showinfo("Camera", "Unlock camera settings first.")
            return
        self.uvc.reset_defaults()
        for w in self.controls_frame.winfo_children():
            w.destroy()
        self.control_vars, self.control_widgets = {}, []
        self.build_controls()

    # =====================================================================
    # Protocols
    def refresh_protocol_list(self, select=None):
        names = protocols.list_protocols()
        self.cb_protocol["values"] = names
        self.cb_protocol_edit["values"] = names
        if select in names:
            self.var_protocol.set(select)
        elif self.var_protocol.get() not in names and names:
            self.var_protocol.set(names[0])
        self.on_protocol_selected()

    def on_protocol_selected(self):
        p = self.selected_protocol()
        if p is None:
            return
        self.unlocked = False
        self.settings["last_protocol"] = p["name"]
        self.load_editor(p)

    def is_locked(self):
        return bool(self.loaded_protocol and self.loaded_protocol.get("builtin")) and not self.unlocked

    def load_editor(self, p):
        self.loaded_protocol = copy.deepcopy(p)
        for w in self.editor.winfo_children():
            w.destroy()
        self.fields = {}
        builtin = bool(p.get("builtin"))
        self.var_lock.set(("LOCKED: built-in protocol. Unlock to edit; changes are saved under a new name."
                           if self.is_locked() else ("Unlocked: use Save As to keep changes." if builtin else "")))
        for b in (self.btn_unlock, self.btn_restore):
            if builtin:
                b.pack(side="left", padx=6)
            else:
                b.pack_forget()
        if p["type"] == "list":
            self._list_editor(p)
        else:
            self._ppi_editor(p)
        self._set_editor_state()
        self.preview_schedule()

    def _field(self, parent, r, c, label, path, value, kind="float", width=8, values=None):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 12, 4), pady=2)
        if kind == "list":
            text = ", ".join(f"{x:g}" for x in value)
        elif kind == "opt_float":
            text = "" if value is None else f"{value:g}"
        elif kind in ("float", "int"):
            text = f"{value:g}"
        else:
            text = "" if value is None else str(value)
        v = tk.StringVar(value=text)
        if values:
            w = ttk.Combobox(parent, textvariable=v, values=values, width=width, state="readonly")
        else:
            w = ttk.Entry(parent, textvariable=v, width=width)
        w.grid(row=r, column=c + 1, sticky="w", pady=2)
        self.fields[path] = (v, kind, w)

    def _list_editor(self, p):
        e = self.editor
        st = p["startle"]
        g = ttk.LabelFrame(e, text="Startle tone", padding=6)
        g.grid(row=0, column=0, sticky="nw")
        self._field(g, 0, 0, "Level (dB SPL)", ("startle", "level_db"), st["level_db"])
        self._field(g, 0, 2, "Rise (ms)", ("startle", "rise_ms"), st["rise_ms"])
        self._field(g, 1, 0, "Plateau (ms)", ("startle", "plateau_ms"), st["plateau_ms"])
        self._field(g, 1, 2, "Fall (ms)", ("startle", "fall_ms"), st["fall_ms"])
        self._field(g, 2, 0, "Background noise (dB SPL, blank = off)", ("background_noise_db",),
                    p.get("background_noise_db"), kind="opt_float")
        self._field(g, 2, 2, "Record after last tone (s)", ("end_padding_s",), p.get("end_padding_s", 30))
        self._field(g, 3, 0, "Assay variant (blank = plain startle)", ("assay_variant",),
                    p.get("assay_variant", ""), kind="str", width=18, values=protocols.ASSAY_VARIANTS)
        self._field(g, 3, 2, "Noise off at (s, blank = stays on)", ("background_noise_off_s",),
                    p.get("background_noise_off_s"), kind="opt_float")

        tf = ttk.LabelFrame(e, text="Tones, one per line: time (s), kHz[, dB]", padding=6)
        tf.grid(row=0, column=1, rowspan=2, sticky="nw", padx=10)
        ttk.Label(tf, text="dB is optional; without it the level above is used.",
                  foreground="#555").pack(anchor="w")
        self.trials_text = tk.Text(tf, width=26, height=12, font=(MONO_FONT, 11))
        self.trials_text.pack()
        self.trials_text.insert("end", "\n".join(
            f"{t['time_s']:g}, {t['freq_hz'] / 1000:g}" + (f", {t['level_db']:g}" if "level_db" in t else "")
            for t in p["trials"]))

        gen = ttk.LabelFrame(e, text="Generate tone list", padding=6)
        gen.grid(row=1, column=0, sticky="nw", pady=6)
        self.gen_vars = {}
        for i, (key, label, default) in enumerate([
                ("first", "First tone (s)", str(protocols.HABITUATION_S)), ("n", "Number of tones", "15"),
                ("isi_min", "Gap min (s)", "15"), ("isi_max", "Gap max (s)", "45"),
                ("freqs", "Frequencies (kHz)", "4, 8, 12, 16, 20")]):
            ttk.Label(gen, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=4)
            v = tk.StringVar(value=default)
            ttk.Entry(gen, textvariable=v, width=16 if key == "freqs" else 7).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w")
            self.gen_vars[key] = v
        self.gen_vars["order"] = tk.StringVar(value="random (balanced)")
        ttk.Combobox(gen, textvariable=self.gen_vars["order"], state="readonly", width=16,
                     values=["random (balanced)", "in order (cycle)"]).grid(row=2, column=3, sticky="w")
        self.btn_generate = ttk.Button(gen, text="Generate", command=self.generate_list)
        self.btn_generate.grid(row=3, column=0, columnspan=4, sticky="w", pady=4)

    def _ppi_editor(self, p):
        e = self.editor
        gen = ttk.LabelFrame(e, text="Session", padding=6)
        gen.grid(row=0, column=0, sticky="nw")
        self._field(gen, 0, 0, "Background noise (dB SPL)", ("background_noise_db",),
                    p.get("background_noise_db"), kind="opt_float")
        self._field(gen, 1, 0, "Habituation before 1st trial (s)", ("acclimation_s",), p["acclimation_s"])
        self._field(gen, 2, 0, "Record after last trial (s)", ("end_padding_s",), p["end_padding_s"])
        self._field(gen, 3, 0, "Inter-trial interval min (s)", ("iti_min_s",), p["iti_min_s"])
        self._field(gen, 4, 0, "Inter-trial interval max (s)", ("iti_max_s",), p["iti_max_s"])
        self._field(gen, 5, 0, "Randomize order", ("randomize",), "yes" if p["randomize"] else "no",
                    kind="bool", values=["yes", "no"])
        self._field(gen, 6, 0, "Random seed (blank = new each run)", ("seed",), p.get("seed"), kind="opt_int")
        self._field(gen, 7, 0, "Assay variant", ("assay_variant",),
                    p.get("assay_variant", "Prepulse Inhibition"), kind="str", width=18,
                    values=protocols.ASSAY_VARIANTS)

        pu = ttk.LabelFrame(e, text="Pulse (startle)", padding=6)
        pu.grid(row=0, column=1, sticky="nw", padx=8)
        pp = p["pulse"]
        self._field(pu, 0, 0, "Stimulus", ("pulse", "stimulus"), pp["stimulus"], kind="str",
                    values=["tone", "noise"])
        self._field(pu, 1, 0, "Frequency (Hz)", ("pulse", "freq_hz"), pp["freq_hz"])
        self._field(pu, 2, 0, "Level (dB SPL)", ("pulse", "level_db"), pp["level_db"])
        self._field(pu, 3, 0, "Rise (ms)", ("pulse", "rise_ms"), pp["rise_ms"])
        self._field(pu, 4, 0, "Plateau (ms)", ("pulse", "plateau_ms"), pp["plateau_ms"])
        self._field(pu, 5, 0, "Fall (ms)", ("pulse", "fall_ms"), pp["fall_ms"])

        pr = ttk.LabelFrame(e, text="Prepulse", padding=6)
        pr.grid(row=0, column=2, sticky="nw", padx=8)
        q = p["prepulse"]
        self._field(pr, 0, 0, "Stimulus", ("prepulse", "stimulus"), q["stimulus"], kind="str",
                    values=["noise", "tone"])
        self._field(pr, 1, 0, "Frequency (Hz, tone only)", ("prepulse", "freq_hz"), q["freq_hz"])
        self._field(pr, 2, 0, "Levels above background (dB)", ("prepulse", "levels_above_bg_db"),
                    q["levels_above_bg_db"], kind="list", width=12)
        self._field(pr, 3, 0, "Rise (ms)", ("prepulse", "rise_ms"), q["rise_ms"])
        self._field(pr, 4, 0, "Plateau (ms)", ("prepulse", "plateau_ms"), q["plateau_ms"])
        self._field(pr, 5, 0, "Fall (ms)", ("prepulse", "fall_ms"), q["fall_ms"])
        self._field(pr, 6, 0, "Lead intervals, onset to onset (ms)", ("lead_intervals_ms",),
                    p["lead_intervals_ms"], kind="list", width=12)

        tr = ttk.LabelFrame(e, text="Trials", padding=6)
        tr.grid(row=1, column=0, columnspan=3, sticky="nw", pady=6)
        self._field(tr, 0, 0, "Pulse-alone block at start", ("start_pulse_alone",), p["start_pulse_alone"], kind="int")
        self._field(tr, 0, 2, "Pulse-alone block at end", ("end_pulse_alone",), p["end_pulse_alone"], kind="int")
        self._field(tr, 1, 0, "Pulse-alone (mixed in)", ("n_pulse_alone",), p["n_pulse_alone"], kind="int")
        self._field(tr, 1, 2, "No-stimulus trials", ("n_no_stim",), p["n_no_stim"], kind="int")
        self._field(tr, 2, 0, "Prepulse+pulse, per level x lead", ("n_prepulse_pulse_each",),
                    p["n_prepulse_pulse_each"], kind="int")
        self._field(tr, 2, 2, "Prepulse-alone, per level", ("n_prepulse_alone_each",),
                    p["n_prepulse_alone_each"], kind="int")

    def _set_editor_state(self):
        locked = self.is_locked()
        for v, kind, w in self.fields.values():
            if isinstance(w, ttk.Combobox):
                w.configure(state="disabled" if locked else "readonly")
            else:
                w.configure(state="disabled" if locked else "normal")
        if self.loaded_protocol["type"] == "list":
            self.trials_text.configure(state="disabled" if locked else "normal",
                                       bg="#eeeeee" if locked else "white")
            self.btn_generate.configure(state="disabled" if locked else "normal")

    def editor_protocol(self):
        """Protocol dict from the editor fields. Raises ValueError with a readable message."""
        p = copy.deepcopy(self.loaded_protocol)
        for path, (v, kind, w) in self.fields.items():
            s = v.get().strip()
            label = " / ".join(path)
            try:
                if kind == "float":
                    val = float(s)
                elif kind == "int":
                    val = int(s)
                elif kind == "opt_float":
                    val = float(s) if s else None
                elif kind == "opt_int":
                    val = int(s) if s else None
                elif kind == "list":
                    val = [float(x) for x in s.replace(";", ",").split(",") if x.strip()]
                elif kind == "bool":
                    val = s == "yes"
                else:
                    val = s
            except ValueError:
                raise ValueError(f"'{s}' is not a valid value for {label}.")
            d = p
            for k in path[:-1]:
                d = d[k]
            d[path[-1]] = val
        if p["type"] == "list":
            trials = []
            for n, line in enumerate(self.trials_text.get("1.0", "end").splitlines(), start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [x for x in line.replace("\t", ",").replace(" ", ",").split(",") if x]
                try:
                    trial = {"time_s": float(parts[0]), "freq_hz": float(parts[1]) * 1000}
                    if len(parts) > 2:
                        trial["level_db"] = float(parts[2])
                    if len(parts) > 3:
                        raise ValueError
                except (ValueError, IndexError):
                    raise ValueError(f"Tone list line {n} should be 'time (s), kHz' or "
                                     f"'time (s), kHz, dB': {line}")
                trials.append(trial)
            p["trials"] = trials
        return p

    def generate_list(self):
        try:
            g = {k: v.get() for k, v in self.gen_vars.items()}
            first, n = float(g["first"]), int(g["n"])
            lo, hi = float(g["isi_min"]), float(g["isi_max"])
            freqs = [float(x) for x in g["freqs"].split(",") if x.strip()]
            if n < 1 or not freqs or lo <= 0 or hi < lo:
                raise ValueError
        except ValueError:
            messagebox.showerror("Generate", "Check the generator values (gap min must be > 0 and <= max).")
            return
        rng = np.random.default_rng()
        if g["order"].startswith("random"):
            seq = (freqs * (n // len(freqs) + 1))[:n]
            rng.shuffle(seq)
        else:
            seq = [freqs[i % len(freqs)] for i in range(n)]
        t, lines = first, []
        for f in seq:
            lines.append(f"{round(t, 3):g}, {f:g}")
            t += rng.uniform(lo, hi)
        self.trials_text.delete("1.0", "end")
        self.trials_text.insert("end", "\n".join(lines))
        self.preview_schedule()

    def preview_schedule(self):
        self.schedule_text.delete("1.0", "end")
        try:
            p = self.editor_protocol()
            trials, total = protocols.build_schedule(p)
            text = protocols.describe_schedule(trials, total)
            if p["type"] == "ppi" and p.get("randomize") and p.get("seed") is None:
                text = "(Random order: each session gets a new order. Set a seed to repeat one.)\n" + text
        except Exception as e:
            text = f"Problem with this protocol: {e}"
        self.schedule_text.insert("end", text)

    def unlock_protocol(self):
        if messagebox.askyesno("Unlock", "Unlock this built-in protocol for editing?\n\n"
                               "Your changes will be saved under a new name. The original "
                               "protocol stays available."):
            self.unlocked = True
            self.var_lock.set("Unlocked: use Save As to keep changes.")
            self._set_editor_state()

    def restore_builtin(self):
        name = self.var_protocol.get()
        if protocols.is_builtin(name) and messagebox.askyesno(
                "Restore", f"Restore the original '{name}' protocol?"):
            protocols.restore_builtin(name)
            self.refresh_protocol_list(name)

    def save_protocol(self):
        if self.loaded_protocol.get("builtin"):
            self.save_protocol_as()
            return
        try:
            p = self.editor_protocol()
            protocols.build_schedule(p)
            protocols.save(p)
            self.log(f"Protocol saved: {p['name']}")
            self.refresh_protocol_list(p["name"])
        except Exception as e:
            messagebox.showerror("Save protocol", str(e))

    def save_protocol_as(self):
        try:
            p = self.editor_protocol()
            protocols.build_schedule(p)
        except Exception as e:
            messagebox.showerror("Save protocol", str(e))
            return
        name = simpledialog.askstring("Save As", "Name for this protocol:", parent=self.root)
        if not name:
            return
        name = name.strip()
        if protocols.is_builtin(name):
            messagebox.showerror("Save As", "That name is reserved for a built-in protocol.")
            return
        if name in protocols.list_protocols() and not messagebox.askyesno("Save As", f"Replace '{name}'?"):
            return
        p["name"] = name
        protocols.save(p)
        self.log(f"Protocol saved: {name}")
        self.refresh_protocol_list(name)

    def delete_protocol(self):
        name = self.var_protocol.get()
        if protocols.is_builtin(name):
            messagebox.showinfo("Delete", "Built-in protocols can't be deleted.")
            return
        if messagebox.askyesno("Delete", f"Delete protocol '{name}'?"):
            protocols.delete(name)
            self.refresh_protocol_list(protocols.TVS_NAME)

    def _new_protocol(self, template):
        name = simpledialog.askstring("New protocol", "Name:", parent=self.root)
        if not name:
            return
        p = copy.deepcopy(template)
        p["name"] = name.strip()
        if protocols.is_builtin(p["name"]):
            messagebox.showerror("New protocol", "That name is reserved.")
            return
        protocols.save(p)
        self.refresh_protocol_list(p["name"])

    def new_list_protocol(self):
        self._new_protocol(protocols.DEFAULT_LIST)

    def new_ppi_protocol(self):
        self._new_protocol(protocols.DEFAULT_PPI)

    # =====================================================================
    # Calibration
    def update_cal_labels(self):
        for key, row in self.cal_rows.items():
            try:
                ref = float(row["meas"].get()) - float(row["test"].get())
            except ValueError:
                ref = None
            if ref is None:
                row["ref"].set("-")
                row["max"].set("-")
                continue
            row["ref"].set(f"{ref:.1f}")
            limit = calibration.NOISE_MAX_DBFS if key == "noise" else calibration.TONE_MAX_DBFS
            row["max"].set(f"{ref + limit:.1f} dB SPL")
        if calibration.is_calibrated(self.cal):
            age = calibration.age_days(self.cal)
            self.var_cal_status.set(f"Saved calibration: {self.cal['date']} ({age:.0f} days old), "
                                    f"{VOLUME_LABEL} {self.cal.get('mac_volume')}")
        else:
            self.var_cal_status.set("NOT CALIBRATED: levels are approximate until you calibrate.")

    def add_cal_freq(self):
        try:
            hz = int(round(float(self.var_add_freq.get()) * 1000))
            if not 100 <= hz <= self.engine.fs / 2 - 100:
                raise ValueError
        except (ValueError, AttributeError):
            messagebox.showerror("Calibration", "Enter a frequency in kHz below half the sample rate.")
            return
        if hz not in self.cal_freqs:
            self.cal_freqs = sorted(self.cal_freqs + [hz])
            self.build_cal_table()
        self.var_add_freq.set("")

    def toggle_cal_play(self, key):
        if not self.engine:
            return
        if self.recording():
            messagebox.showwarning("Calibration", "Not available during a session.")
            return
        if self.cal_playing == key:
            self.stop_cal_sound()
            return
        self.stop_cal_sound()
        try:
            dbfs = float(self.cal_rows[key]["test"].get())
        except ValueError:
            messagebox.showerror("Calibration", "Test level must be a number (dBFS, e.g. -30).")
            return
        limit = calibration.NOISE_MAX_DBFS if key == "noise" else calibration.TONE_MAX_DBFS
        if dbfs > limit:
            messagebox.showerror("Calibration", f"Test level must be at most {limit:g} dBFS.")
            return
        if key == "noise":
            self._noise_before_cal = self.engine.noise_target
            self.engine.set_noise_dbfs(dbfs)
        else:
            self.engine.set_cal_tone(key, dbfs)
        self.cal_playing = key
        self.cal_rows[key]["btn"].configure(text="Stop")

    def stop_cal_sound(self):
        if self.engine and self.cal_playing is not None:
            if self.cal_playing == "noise":
                self.engine.noise_target = getattr(self, "_noise_before_cal", 0.0)
            else:
                self.engine.set_cal_tone(0, None)
            if self.cal_playing in self.cal_rows:
                self.cal_rows[self.cal_playing]["btn"].configure(text="Play")
        self.cal_playing = None

    def play_cal_burst(self, freq):
        if not self.engine or self.recording():
            return
        p = self.selected_protocol() or protocols.BUILTINS[protocols.TVS_NAME]
        st = p.get("startle") or p.get("pulse")
        try:
            dbfs = float(self.cal_rows[freq]["test"].get())
        except ValueError:
            return
        stim = {"stimulus": "tone", "freq_hz": freq, "rise_ms": st["rise_ms"],
                "plateau_ms": st["plateau_ms"], "fall_ms": st["fall_ms"]}
        self.engine.play_now(make_stimulus(stim, dbfs, self.engine.fs))

    def save_calibration(self):
        self.stop_cal_sound()
        n = 0
        for key, row in self.cal_rows.items():
            m = row["meas"].get().strip()
            if not m:
                continue
            try:
                calibration.set_measurement(self.cal, key, float(row["test"].get()), float(m))
                n += 1
            except ValueError:
                messagebox.showerror("Calibration", f"Bad number in row {key}.")
                return
        if n == 0:
            messagebox.showinfo("Calibration", "Type at least one measured dB SPL value first.")
            return
        vol, muted = sysutil.output_volume()
        self.cal.update(weighting=self.var_weighting.get().split()[0], mac_volume=vol,
                        output_device=self.engine.actual_device if self.engine else None,
                        channel_mode=self.settings["channel_mode"], sample_rate=self.settings["sample_rate"])
        calibration.save(self.cal)
        self.update_cal_labels()
        self.log(f"Calibration saved ({n} measurements, {VOLUME_LABEL} {vol}).")
        messagebox.showinfo("Calibration", f"Saved {n} measurements.\n\nKeep the {VOLUME_LABEL} at {vol} and "
                                           "the amplifier knob where it is.")

    def check_protocol_levels(self):
        p = self.selected_protocol()
        if not p:
            return
        messagebox.showinfo("Level check", "\n".join(self.level_problems(p, verbose=True)) or "All OK")

    def level_problems(self, p, verbose=False):
        out, seen = [], set()
        stims = protocols.stimuli_used(p)
        if p.get("background_noise_db") is not None:
            stims.append({"stimulus": "noise", "level_db": p["background_noise_db"], "background": True})
        for s in stims:
            key = (s["stimulus"], s.get("freq_hz") if s["stimulus"] == "tone" else 0, s["level_db"])
            if key in seen:
                continue
            seen.add(key)
            dbfs, status, ok = calibration.stimulus_dbfs(self.cal, s, s["level_db"])
            what = ("background noise" if s.get("background") else
                    "noise" if s["stimulus"] == "noise" else f"{s['freq_hz'] / 1000:g} kHz")
            if not ok:
                out.append(f"TOO LOUD: {what} at {s['level_db']:g} dB SPL needs {dbfs:.1f} dBFS "
                           "(turn the amplifier up and recalibrate)")
            elif verbose or status != "calibrated":
                out.append(f"{what} at {s['level_db']:g} dB SPL -> {dbfs:.1f} dBFS ({status})")
        return out

    # =====================================================================
    # Session
    def _refresh_experimenters(self):
        self.cb_experimenter["values"] = [ADD_NAME_LABEL] + self.settings["experimenters"]

    def on_experimenter(self, _event=None):
        if self.var_experimenter.get() != ADD_NAME_LABEL:
            self.settings["last_experimenter"] = self.var_experimenter.get()
            self.save_settings()
            return
        name = simpledialog.askstring("Add a name", "Experimenter name:", parent=self.root)
        name = (name or "").strip()
        if name:
            if name not in self.settings["experimenters"]:
                self.settings["experimenters"].append(name)
                self.settings["experimenters"].sort(key=str.lower)
            self.settings["last_experimenter"] = name
            self.save_settings()
            self._refresh_experimenters()
            self.var_experimenter.set(name)
        else:
            self.var_experimenter.set(self.settings.get("last_experimenter", ""))

    def choose_data_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_data_dir.get())
        if d:
            self.var_data_dir.set(d)
            self.settings["data_dir"] = d
            self.save_settings()

    def preflight(self):
        """(errors, warnings, protocol, trials, total_s)."""
        errors, warnings = [], []
        exp = self.var_experimenter.get()
        if not exp or exp == ADD_NAME_LABEL:
            errors.append("Choose the experimenter.")
        if not self.animal_vars["animal_id"].get().strip():
            errors.append("Enter the Animal ID.")
        dob = self.animal_vars["dob"].get().strip()
        if dob:
            try:
                dt.date.fromisoformat(dob)
            except ValueError:
                errors.append("Date of birth must be written YYYY-MM-DD (e.g. 2026-08-15).")
        for key, label in (("trial_day", "Trial day"), ("session_number", "Session number")):
            val = self.animal_vars[key].get().strip()
            if val and not (val.isdigit() and int(val) >= 1):
                errors.append(f"{label} must be a whole number (1, 2, ...).")
        for key in ("arena", "camera_label"):
            if not NAME_PART_RE.fullmatch(self.settings.get(key, "")):
                errors.append("Set the Arena and Camera label on the Settings tab "
                              "(letters, digits and - only).")
                break
        if not self.engine or not self.engine.running:
            errors.append("Sound output is not running (see Settings).")
        cam = self.camera
        if not cam or not cam.alive or cam.frame_count == 0:
            errors.append("The camera is not delivering video.")
        p = self.selected_protocol()
        trials = total = None
        if not p:
            errors.append("Choose a protocol.")
        else:
            try:
                trials, total = protocols.build_schedule(p)
            except Exception as e:
                errors.append(f"Protocol problem: {e}")
            for line in self.level_problems(p):
                (errors if line.startswith("TOO LOUD") else warnings).append(line)

        if not calibration.is_calibrated(self.cal):
            warnings.append("Speaker is NOT calibrated: dB SPL levels are approximate.")
        else:
            age = calibration.age_days(self.cal)
            if age is not None and age > float(self.settings["calibration_max_age_days"]):
                warnings.append(f"Calibration is {age:.0f} days old.")
            vol, muted = sysutil.output_volume()
            if muted:
                errors.append("The computer's sound is MUTED.")
            elif self.cal.get("mac_volume") is not None and vol != self.cal["mac_volume"]:
                warnings.append(f"{VOLUME_LABEL} is {vol} but was {self.cal['mac_volume']} at calibration.")
            if self.engine and self.cal.get("output_device") not in (None, self.engine.actual_device):
                warnings.append(f"Sound output is '{self.engine.actual_device}' but calibration used "
                                f"'{self.cal['output_device']}'.")
        if cam and cam.frame_count:
            fps = cam.measured_fps()
            if fps and abs(fps - cam.fps) / cam.fps > 0.05:
                warnings.append(f"Camera is delivering {fps:.1f} fps instead of {cam.fps} "
                                "(missing frames will be repeated and logged).")
        if self.uvc and not self.var_cam_lock.get():
            warnings.append("Camera settings are not locked (Camera tab).")
        if not self.settings.get("mic_device"):
            warnings.append("No microphone selected: there will be no audio check track.")
        free = sysutil.free_gb(self.settings["data_dir"]) if self.settings["data_dir"] else None
        if free is not None and free < 5:
            warnings.append(f"Only {free:.1f} GB free disk space.")
        where = ("Settings > System > Notifications" if IS_WINDOWS else "Control Center > Focus")
        warnings.append(f"Turn on Do Not Disturb ({where}) so alert sounds can't "
                        "startle the animal, and close other apps that make sounds.")
        return errors, warnings, p, trials, total

    def on_start(self):
        if self.busy():
            return
        self.stop_cal_sound()
        errors, warnings, p, trials, total = self.preflight()
        if errors:
            messagebox.showerror("Can't start", "\n\n".join(errors))
            return
        msg = (f"Protocol: {p['name']}  ({len(trials)} trials, {total / 60:.1f} min)\n"
               f"Animal: {self.animal_vars['animal_id'].get()}   Experimenter: {self.var_experimenter.get()}\n\n"
               + "\n\n".join("- " + w for w in warnings) + "\n\nStart the session?")
        if not messagebox.askokcancel("Start session", msg):
            return
        self._pending = (p, trials, total)
        self.btn_start.configure(state="disabled")
        self._set_session_inputs("disabled")
        self._countdown = int(self.settings.get("countdown_s", 5))
        self._tick_countdown()

    def _tick_countdown(self):
        if self._countdown is None:
            return
        if self._countdown > 0:
            self.big_status.set(f"Starting in {self._countdown}...")
            self._countdown -= 1
            self.root.after(1000, self._tick_countdown)
            return
        self._countdown = None
        self._begin_session()

    def _begin_session(self):
        p, trials, total = self._pending
        meta = {"experimenter": self.var_experimenter.get(),
                **{k: v.get().strip() for k, v in self.animal_vars.items()}}
        uvc_values = {}
        if self.uvc:
            if self.var_cam_lock.get() and self.settings.get("camera_controls"):
                self.uvc.apply_all(self.settings["camera_controls"])
            try:
                uvc_values = self.uvc.read_all()
            except Exception:
                pass
        self.session = Session(engine=self.engine, camera=self.camera, cal=copy.deepcopy(self.cal),
                               protocol=p, trials=trials, total_s=total, meta=meta,
                               settings=dict(self.settings), uvc_values=uvc_values, log=self.log)
        try:
            self.session.start()
        except Exception as e:
            self.log(f"Could not start: {e}")
            messagebox.showerror("Start session", str(e))
            self.session = None
            self.btn_start.configure(state="normal")
            self._set_session_inputs("normal")
            self.big_status.set("")
            return
        self.btn_next.configure(state="disabled")

    def on_stop(self):
        """Always available: cancels the countdown, stops a session, or silences all sound."""
        if self._countdown is not None:
            self._countdown = None
            self.big_status.set("Cancelled")
            self.btn_start.configure(state="normal")
            self._set_session_inputs("normal")
            return
        if self.recording():
            if messagebox.askyesno("Stop", "Stop the session now? Everything recorded so far will be saved."):
                self._end_session(early=True)
            return
        self.stop_cal_sound()
        if self.engine:
            if self.engine.noise_target > 0:
                self.log("Background noise off (STOP).")
            self.engine.set_noise_dbfs(None)
            self.engine.set_cal_tone(0, None)
            self.engine.cancel_all()
        self.big_status.set("All sound stopped")

    def _end_session(self, early):
        s = self.session
        s.stop(early=early)
        self.big_status.set("Saving...")
        self.finalize_thread = threading.Thread(target=self._finalize, args=(s,), daemon=True)
        self.finalize_thread.start()

    def _finalize(self, s):
        try:
            s.finalize()
            self.log(s.result_text)
        except Exception:
            self.log("ERROR saving session:\n" + traceback.format_exc())

    def on_next_animal(self):
        if self.busy():
            return
        for k, v in self.animal_vars.items():
            if k not in ("cohort", "trial_day"):       # usually the same for the next animal
                v.set("U" if k == "sex" else "")
        self.session = None
        self.btn_next.configure(state="disabled")
        self.btn_start.configure(state="normal")
        self._set_session_inputs("normal")
        self.big_status.set("Ready")
        self.entry_animal.focus_set()

    def _set_session_inputs(self, state):
        for w in (self.cb_protocol, self.cb_protocol_edit, self.cb_experimenter):
            w.configure(state="readonly" if state == "normal" else "disabled")

    # =====================================================================
    # Periodic updates
    def _tick_preview(self):
        try:
            cam = self.camera
            if cam is not None and cam.latest is not None and cam.frame_count != self._preview_count:
                self._preview_count = cam.frame_count
                img = Image.fromarray(cam.latest)
                img.thumbnail(self.preview_box, Image.BILINEAR)
                img = img.convert("RGB")
                d = ImageDraw.Draw(img)
                s = self.session
                if s and s.state == "recording":
                    text = f"REC {s.elapsed():7.1f} s   frame {s.recorder.n_frames - 1}"
                    last = s.last_stim_perf()
                    if last and 0 <= time.perf_counter() - last < 0.3:
                        d.rectangle([0, 0, img.width - 1, img.height - 1], outline=(255, 0, 0), width=10)
                        d.rectangle([0, 0, 120, 30], fill=(255, 0, 0))
                        d.text((10, 8), "STIMULUS", fill=(255, 255, 255))
                    d.text((10, img.height - 20), text, fill=(255, 60, 60))
                else:
                    d.text((10, img.height - 20), f"PREVIEW  {cam.measured_fps():.1f} fps", fill=(80, 255, 80))
                self._photo = ImageTk.PhotoImage(img)
                self.preview.configure(image=self._photo, width=img.width, height=img.height)
        except Exception as e:
            self.log(f"Preview error: {e}")
        self.root.after(30, self._tick_preview)

    def _tick_status(self):
        self._drain_log()
        sv = self.status_vars
        cam = self.camera
        if cam is None:
            sv["Camera"].set("not running")
            sv["Video"].set("-")
        elif cam.error:
            sv["Camera"].set("ERROR (see log)")
        else:
            sv["Camera"].set(cam.name)
            sv["Video"].set(f"{cam.width}x{cam.height}  {cam.measured_fps():.1f}/{cam.fps} fps")

        s = self.session
        if s and s.state == "recording":
            if s.poll():
                self._end_session(early=s.stopped_early)
            el = s.elapsed()
            sv["Recording"].set("RECORDING")
            sv["Elapsed"].set(f"{el:7.1f} / {s.total_s:.1f} s")
            nt = s.next_trial()
            if nt:
                sv["Next stimulus"].set(f"trial {nt['trial']} ({nt['type']}) in {nt['ref_time_s'] - el:.1f} s")
                sv["Trial"].set(f"{nt['trial'] - 1} / {len(s.trials)} done")
                self.big_status.set(f"RECORDING  {el:5.0f} s")
            else:
                sv["Next stimulus"].set("none (recording until end)")
                sv["Trial"].set(f"{len(s.trials)} / {len(s.trials)} done")
                self.big_status.set(f"RECORDING  ending in {s.total_s - el:.0f} s")
            sv["Dropped frames"].set(f"{s.recorder.n_duplicated}")
            sv["Microphone"].set(f"{s.mic.level_db:6.1f} dBFS" if s.mic else "not recording")
        elif s and s.state == "finalizing":
            sv["Recording"].set("saving files...")
        elif s and s.state in ("done", "failed"):
            sv["Recording"].set("saved" if s.state == "done" else "SAVE FAILED (see log)")
            if str(self.btn_next["state"]) == "disabled" and (not self.finalize_thread or not self.finalize_thread.is_alive()):
                self.btn_next.configure(state="normal")
                self.big_status.set("Done: press Next animal" if s.state == "done" else "Save failed")
        else:
            sv["Recording"].set("idle")
            sv["Elapsed"].set("-")
            sv["Next stimulus"].set("-")
            sv["Trial"].set("-")
            sv["Dropped frames"].set("-")
            sv["Microphone"].set(self.settings.get("mic_device") or "none")
            if self._countdown is None and self.big_status.get().startswith("Starting"):
                self.big_status.set("")
            if self.engine and not self.busy():
                self.engine.finished.clear()
            if not self.big_status.get():
                self.big_status.set("Ready")

        if self.engine:
            sv["Background noise"].set("ON" if self.engine.noise_target > 0 else "off")
            self.btn_noise.configure(text="Stop background noise" if self.engine.noise_target > 0
                                     else "Start background noise")
        self._status_ticks = getattr(self, "_status_ticks", 0) + 1
        if self._status_ticks % 25 == 1:
            vol, muted = sysutil.output_volume()
            sv[VOLUME_LABEL].set("MUTED" if muted else f"{vol}")
        self.root.after(200, self._tick_status)

    # =====================================================================
    def apply_settings(self):
        if self.busy():
            messagebox.showwarning("Settings", "Can't change settings during a session.")
            return
        arena, label = self.var_arena.get().strip(), self.var_camera_label.get().strip()
        for what, val in (("Arena", arena), ("Camera label", label)):
            if not NAME_PART_RE.fullmatch(val):
                messagebox.showerror("Settings", f"{what} may use only letters, digits and - "
                                                 "(no spaces or _), e.g. ASR1 or Side.")
                return
        try:
            self.settings.update(
                arena=arena, room=self.var_room.get().strip(), camera_label=label,
                output_device="" if self.var_out_dev.get() == SYSTEM_DEFAULT else self.var_out_dev.get(),
                channel_mode=self.var_channel.get(),
                sample_rate=int(self.var_rate.get()),
                mic_device="" if self.var_mic.get() == NO_MIC else self.var_mic.get(),
                keep_noise_after_session=bool(self.var_keep_noise.get()),
                countdown_s=int(self.var_countdown.get()),
                calibration_max_age_days=float(self.var_cal_age.get()),
                video_crf=int(self.var_crf.get()),
                video_preset=self.var_preset.get())
        except ValueError:
            messagebox.showerror("Settings", "Check that the numbers are valid.")
            return
        self.save_settings()
        self.stop_cal_sound()
        self.start_audio()
        self.log("Settings saved.")

    def on_close(self):
        if self.busy():
            if not messagebox.askyesno("Quit", "A session is running. Stop it, save, and quit?"):
                return
            if self.recording():
                self.session.stop(early=True)
                self.big_status.set("Saving...")
                self.root.update()
                try:
                    self.session.finalize()
                except Exception:
                    pass
            elif self.finalize_thread:
                self.finalize_thread.join()
        self.save_settings()
        if self.camera:
            self.camera.stop()
        if self.engine:
            self.engine.stop()
        if self.caffeinate:
            self.caffeinate.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        App(root)
    except Exception:
        messagebox.showerror("Boom Box", traceback.format_exc())
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
