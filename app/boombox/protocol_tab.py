"""The Protocol tab: what a protocol will run, and the tools to make and change one.

On the left, a summary card and a timeline show what will run; the full trial list is
in a tall column on the right. Editing is tucked into a bar below the timeline and opens
with Edit. Built-in protocols can't be changed; Copy... makes an editable version under
a new name. Everything shown follows the editor as you type.
"""

import copy
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, simpledialog, ttk

import numpy as np

from . import protocols

# The three kinds of protocol, in the words the screen uses.
KINDS = {
    "list": ("Stimulus list",
             "You type each stimulus: its time, its frequency (or noise) and, if you like, "
             "its own level. Tone Volume Sensitivity, Startle Habituation and Hearing Test "
             "are this kind."),
    "ppi": ("Prepulse inhibition (PPI)",
            "Boom Box builds a shuffled schedule of pulse-alone, prepulse+pulse, "
            "prepulse-alone and no-stimulus trials from the levels and counts you set."),
    "io": ("Input/output curve (I/O)",
           "Startle bursts at a set of levels, each level once per block, with the blocks "
           "shuffled. The built-in I/O protocol is this kind."),
}
PREVIEW_DELAY_MS = 300
TIMELINE_W, TIMELINE_H = 470, 170
TABLE_ROWS = 34
EDIT_HINT = "Press Edit to change this protocol's settings and stimuli."
EDIT_BUILTIN_NOTE = "Built-in protocols can't be changed. Press Copy... to make your own version, then edit that."
EDITING_NOTE = "Change the settings below. The summary, timeline and trials follow your changes."
UNSAVED_NOTE = "Unsaved changes. Sessions use the saved version until you press Save."


def template(kind):
    """A fresh protocol of this kind, for New..."""
    if kind == "list":
        p = copy.deepcopy(protocols.DEFAULT_LIST)
    elif kind == "ppi":
        p = copy.deepcopy(protocols.DEFAULT_PPI)
    else:
        p = copy.deepcopy(protocols.BUILTINS[protocols.IO_NAME])
        p["reference"] = ""
    p.pop("builtin", None)
    return p


def parse_list_line(line):
    """One line of a list protocol: 'time (s), kHz[, dB]', with 'noise' in place of
    the kHz for white noise. Raises ValueError or IndexError if it can't be read."""
    parts = [x for x in line.replace("\t", ",").replace(" ", ",").split(",") if x]
    if not 2 <= len(parts) <= 3:
        raise ValueError(line)
    trial = {"time_s": float(parts[0])}
    if parts[1].lower() == "noise":
        trial["stimulus"] = "noise"
    else:
        trial["freq_hz"] = float(parts[1]) * 1000
    if len(parts) > 2:
        trial["level_db"] = float(parts[2])
    return trial


def _list_line_text(t):
    what = "noise" if t.get("stimulus") == "noise" else f"{t['freq_hz'] / 1000:g}"
    return f"{t['time_s']:g}, {what}" + (f", {t['level_db']:g}" if "level_db" in t else "")


def _gen_item(x):
    x = x.strip()
    return "noise" if x.lower() == "noise" else float(x)


def _same(edited, saved):
    """True if the editor's protocol matches the saved one (blank fields the saved file
    leaves out count as the same)."""
    a = {k: v for k, v in edited.items() if not (k not in saved and v in ("", None))}
    return a == saved


class NewProtocolDialog:
    """Asks for a name and the kind of protocol. .result is (name, kind) or None."""

    def __init__(self, parent):
        self.result = None
        self.top = top = tk.Toplevel(parent)
        top.title("New protocol")
        top.transient(parent.winfo_toplevel())
        top.resizable(False, False)
        f = ttk.Frame(top, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Name:").grid(row=0, column=0, sticky="w")
        self.var_name = tk.StringVar()
        entry = ttk.Entry(f, textvariable=self.var_name, width=32)
        entry.grid(row=0, column=1, sticky="w", pady=(0, 8))
        ttk.Label(f, text="Kind:").grid(row=1, column=0, sticky="nw")
        self.var_kind = tk.StringVar(value="list")
        kinds = ttk.Frame(f)
        kinds.grid(row=1, column=1, sticky="w")
        for i, (key, (title, about)) in enumerate(KINDS.items()):
            ttk.Radiobutton(kinds, text=title, value=key, variable=self.var_kind).grid(
                row=2 * i, column=0, sticky="w")
            ttk.Label(kinds, text=about, wraplength=380, foreground="#555", justify="left").grid(
                row=2 * i + 1, column=0, sticky="w", padx=(22, 0), pady=(0, 6))
        buttons = ttk.Frame(f)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(buttons, text="Create", command=self._ok).pack(side="right", padx=6)
        top.bind("<Return>", lambda e: self._ok())
        top.bind("<Escape>", lambda e: top.destroy())
        entry.focus_set()
        top.grab_set()

    def _ok(self):
        self.result = (self.var_name.get().strip(), self.var_kind.get())
        self.top.destroy()


def ask_new_protocol(parent):
    """(name, kind) from the New protocol window, or None if cancelled."""
    d = NewProtocolDialog(parent)
    parent.wait_window(d.top)
    return d.result


class ProtocolTab:
    def __init__(self, parent, var_protocol, settings, log, on_names, mono_font):
        """on_names(names) is called whenever the protocol list changes (to refresh other
        protocol menus); var_protocol is shared with them."""
        self.parent = parent
        self.var = var_protocol
        self.settings = settings
        self.log = log
        self.on_names = on_names
        self.mono_font = mono_font
        self.loaded = None          # the saved protocol shown
        self.editing = False
        self.fields = {}            # path -> (StringVar, kind, widget, label)
        self.trials_text = None
        self.trials = []
        self.total_s = 0.0
        self._preview_job = None
        self._bold = tkfont.nametofont("TkDefaultFont").copy()
        self._bold.configure(weight="bold")
        self._title = tkfont.nametofont("TkDefaultFont").copy()
        self._title.configure(weight="bold", size=self._title.cget("size") + 4)

        top = ttk.Frame(parent)
        top.pack(fill="x")
        ttk.Label(top, text="Protocol:").pack(side="left")
        self.combo = ttk.Combobox(top, textvariable=self.var, state="readonly", width=28)
        self.combo.pack(side="left", padx=4)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.on_selected())
        self.btn_new = ttk.Button(top, text="New...", command=self.new_protocol)
        self.btn_copy = ttk.Button(top, text="Copy...", command=self.copy_protocol)
        self.btn_edit = ttk.Button(top, text="Edit", command=self.edit_protocol)
        self.btn_delete = ttk.Button(top, text="Delete", command=self.delete_protocol)
        for b in (self.btn_new, self.btn_copy, self.btn_edit, self.btn_delete):
            b.pack(side="left", padx=2)

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True, pady=6)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nw")

        # Summary card: what this protocol runs.
        card = ttk.LabelFrame(left, text="Summary", padding=8)
        card.pack(fill="x")
        self.var_name = tk.StringVar()
        self.var_kind = tk.StringVar()
        ttk.Label(card, textvariable=self.var_name, font=self._title).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(card, textvariable=self.var_kind, foreground="#555").grid(row=1, column=0, columnspan=2,
                                                                            sticky="w", pady=(0, 6))
        self.facts = ttk.Frame(card)
        self.facts.grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(card, text="Reference", foreground="#555").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.var_reference = tk.StringVar()
        self.entry_reference = ttk.Entry(card, textvariable=self.var_reference, width=46, state="readonly")
        self.entry_reference.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        # Timeline: one dot per stimulus, by time and level.
        tl = ttk.LabelFrame(left, text="Timeline", padding=6)
        tl.pack(fill="x", pady=(8, 0))
        self.timeline = tk.Canvas(tl, width=TIMELINE_W, height=TIMELINE_H, bg="white", highlightthickness=0)
        self.timeline.pack(fill="x")
        self.timeline.bind("<Configure>", lambda e: self.draw_timeline())

        # Editing bar: collapsed until Edit is pressed.
        self.edit_bar = ttk.LabelFrame(left, text="Edit", padding=8)
        self.edit_bar.pack(fill="x", pady=(8, 0))
        head = ttk.Frame(self.edit_bar)
        head.pack(fill="x")
        self.var_note = tk.StringVar()
        self.lbl_note = ttk.Label(head, textvariable=self.var_note, foreground="#555", wraplength=420,
                                  justify="left")
        self.lbl_note.pack(side="left", anchor="w")
        self.btn_cancel = ttk.Button(head, text="Cancel", command=self.cancel_edit)
        self.btn_save = ttk.Button(head, text="Save", command=self.save_protocol)
        self.editor = ttk.Frame(self.edit_bar)

        # Trials: the full schedule, in a tall column.
        right = ttk.LabelFrame(body, text="Trials: what will run (updates as you edit)", padding=6)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.var_problem = tk.StringVar()
        ttk.Label(right, textvariable=self.var_problem, foreground="#b00020", wraplength=420,
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        cols = ("n", "time", "type", "sound")
        self.table = ttk.Treeview(right, columns=cols, show="headings", height=TABLE_ROWS)
        for c, text, w, anchor in (("n", "#", 40, "e"), ("time", "Time (s)", 80, "e"),
                                   ("type", "Type", 120, "w"), ("sound", "Sound", 260, "w")):
            self.table.heading(c, text=text, anchor=anchor)
            self.table.column(c, width=w, anchor=anchor, stretch=(c == "sound"))
        ys = ttk.Scrollbar(right, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=ys.set)
        self.table.grid(row=1, column=0, sticky="nsew")
        ys.grid(row=1, column=1, sticky="ns")

    # -- choosing ---------------------------------------------------------
    @property
    def builtin(self):
        return bool(self.loaded and self.loaded.get("builtin"))

    def refresh(self, select=None, edit=False):
        names = protocols.list_protocols()
        self.combo["values"] = names
        self.on_names(names)
        if select in names:
            self.var.set(select)
        elif self.var.get() not in names and names:
            self.var.set(names[0])
        self.on_selected(edit=edit)

    def on_selected(self, edit=False):
        name = self.var.get()
        if self.loaded and name != self.loaded["name"] and not self._ok_to_leave():
            self.var.set(self.loaded["name"])
            return
        try:
            p = protocols.load(name)
        except KeyError:
            return
        self.settings["last_protocol"] = p["name"]
        self.editing = edit and not p.get("builtin")
        self.load_editor(p)

    def has_unsaved_changes(self):
        if not self.loaded or self.builtin:
            return False
        try:
            return not _same(self.editor_protocol(), self.loaded)
        except ValueError:
            return True

    def _ok_to_leave(self):
        if not self.has_unsaved_changes():
            return True
        return messagebox.askyesno(
            "Unsaved changes", f"'{self.loaded['name']}' has unsaved changes.\n\nDiscard them?")

    # -- buttons -----------------------------------------------------------
    def _name_problem(self, name):
        if not name:
            return "Enter a name."
        if protocols.is_builtin(name):
            return f"'{name}' is the name of a built-in protocol. Choose a different name."
        if name in protocols.list_protocols():
            return f"A protocol called '{name}' already exists. Choose a different name."
        return None

    def _save_new(self, p, title):
        """Save a protocol under a name not used yet and open it for editing. False if it failed."""
        problem = self._name_problem(p["name"])
        if problem:
            messagebox.showerror(title, problem)
            return False
        p.pop("builtin", None)
        try:
            protocols.save(p)
        except ValueError as e:
            messagebox.showerror(title, str(e))
            return False
        self.log(f"Protocol saved: {p['name']}")
        self.loaded = None
        self.refresh(p["name"], edit=True)
        return True

    def new_protocol(self):
        if not self._ok_to_leave():
            return
        answer = ask_new_protocol(self.parent)
        if not answer:
            return
        name, kind = answer
        p = template(kind)
        p["name"] = name
        self._save_new(p, "New protocol")

    def copy_protocol(self):
        """Save what's shown under a new name and open the copy for editing."""
        try:
            p = self.editor_protocol()
            protocols.build_schedule(p)
        except Exception as e:
            messagebox.showerror("Copy protocol", f"This protocol can't be copied yet: {e}")
            return
        name = simpledialog.askstring("Copy protocol", "Name for the copy:", parent=self.parent,
                                      initialvalue=f"{p['name']} copy")
        if name is None:
            return
        p["name"] = name.strip()
        self._save_new(p, "Copy protocol")

    def edit_protocol(self):
        if not self.loaded:
            return
        if self.builtin:
            if messagebox.askyesno("Edit", f"Built-in protocols can't be changed.\n\nMake your own copy "
                                           f"of '{self.loaded['name']}' to edit?"):
                self.copy_protocol()
            return
        self.editing = True
        self._show_edit_state()

    def cancel_edit(self):
        if self.has_unsaved_changes() and not messagebox.askyesno(
                "Cancel", "Discard your changes to this protocol?"):
            return
        self.editing = False
        self.load_editor(self.loaded)

    def save_protocol(self):
        if self.builtin:
            return
        try:
            p = self.editor_protocol()
            protocols.build_schedule(p)
            protocols.save(p)
        except Exception as e:
            messagebox.showerror("Save protocol", str(e))
            return
        self.log(f"Protocol saved: {p['name']}")
        self.loaded = None
        self.refresh(p["name"])

    def delete_protocol(self):
        if self.builtin or not self.loaded:
            return
        name = self.loaded["name"]
        if messagebox.askyesno("Delete", f"Delete the protocol '{name}'?\n\nThis can't be undone."):
            protocols.delete(name)
            self.log(f"Protocol deleted: {name}")
            self.loaded = None
            self.refresh(protocols.TVS_NAME)

    # -- editor ------------------------------------------------------------
    def load_editor(self, p):
        self.loaded = copy.deepcopy(p)
        for w in self.editor.winfo_children():
            w.destroy()
        self.fields = {}
        self.trials_text = None
        {"list": self._list_editor, "ppi": self._ppi_editor, "io": self._io_editor}[p["type"]](p)
        ref = ttk.Frame(self.editor)
        ref.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._field(ref, 0, 0, "Reference (paper the protocol comes from, e.g. a DOI link)", ("reference",),
                    p.get("reference", ""), kind="str", width=48)
        self._show_edit_state()

    def _field(self, parent, r, c, label, path, value, kind="float", width=8, values=None):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 12, 4), pady=2)
        if kind == "list":
            text = ", ".join(f"{x:g}" for x in value)
        elif kind in ("opt_float", "opt_int"):
            text = "" if value is None else f"{value:g}"
        elif kind in ("float", "int"):
            text = f"{value:g}"
        elif kind == "khz":
            text = f"{value / 1000:g}"
        else:
            text = "" if value is None else str(value)
        v = tk.StringVar(value=text)
        if values:
            w = ttk.Combobox(parent, textvariable=v, values=values, width=width, state="readonly")
        else:
            w = ttk.Entry(parent, textvariable=v, width=width)
        w.grid(row=r, column=c + 1, sticky="w", pady=2)
        v.trace_add("write", lambda *a: self.schedule_preview())
        self.fields[path] = (v, kind, w, label)

    def _list_editor(self, p):
        e = self.editor
        st = p["startle"]
        s = ttk.LabelFrame(e, text="Session", padding=6)
        s.grid(row=0, column=1, sticky="nw", padx=(10, 0))
        self._field(s, 0, 0, "Background noise (dB SPL, blank = off)", ("background_noise_db",),
                    p.get("background_noise_db"), kind="opt_float")
        self._field(s, 1, 0, "Record after last stimulus (s)", ("end_padding_s",), p.get("end_padding_s", 30))
        self._field(s, 2, 0, "Assay variant (blank = plain startle)", ("assay_variant",),
                    p.get("assay_variant", ""), kind="str", width=18, values=protocols.ASSAY_VARIANTS)

        g = ttk.LabelFrame(e, text="Default startle tone", padding=6)
        g.grid(row=0, column=0, sticky="nw")
        self._field(g, 0, 0, "Level (dB SPL)", ("startle", "level_db"), st["level_db"])
        ttk.Label(g, text="for lines without their own dB", foreground="#555").grid(
            row=1, column=0, columnspan=2, sticky="w")
        self._field(g, 2, 0, "Rise (ms)", ("startle", "rise_ms"), st["rise_ms"])
        self._field(g, 3, 0, "Plateau (ms)", ("startle", "plateau_ms"), st["plateau_ms"])
        self._field(g, 4, 0, "Fall (ms)", ("startle", "fall_ms"), st["fall_ms"])

        tf = ttk.LabelFrame(e, text="Stimuli, one per line", padding=6)
        tf.grid(row=1, column=0, sticky="nw", pady=(6, 0))
        ttk.Label(tf, text="time (s), kHz[, dB]\n"
                           "Write noise in place of the kHz for a white-noise\n"
                           "burst, e.g. 300, noise, 110. Without a dB, the\n"
                           "default level is used.",
                  foreground="#555", justify="left").pack(anchor="w")
        self.trials_text = tk.Text(tf, width=26, height=12, font=(self.mono_font, 11))
        self.trials_text.pack()
        self.trials_text.insert("end", "\n".join(_list_line_text(t) for t in p["trials"]))
        self.trials_text.edit_modified(False)
        self.trials_text.bind("<<Modified>>", self._on_text_modified)

        gen = ttk.LabelFrame(e, text="Fill the list automatically", padding=6)
        gen.grid(row=1, column=1, sticky="nw", padx=(10, 0), pady=(6, 0))
        self.gen_vars = {}
        for i, (key, label, default) in enumerate([
                ("first", "First stimulus (s)", str(protocols.HABITUATION_S)),
                ("n", "Number of stimuli", "15"),
                ("isi_min", "Gap min (s)", "15"), ("isi_max", "Gap max (s)", "45"),
                ("freqs", "Frequencies (kHz or noise)", "4, 8, 12, 16, 20")]):
            ttk.Label(gen, text=label).grid(row=i, column=0, sticky="w", padx=(0, 4))
            v = tk.StringVar(value=default)
            ttk.Entry(gen, textvariable=v, width=16 if key == "freqs" else 7).grid(
                row=i, column=1, sticky="w", pady=1)
            self.gen_vars[key] = v
        ttk.Label(gen, text="Order").grid(row=5, column=0, sticky="w", padx=(0, 4))
        self.gen_vars["order"] = tk.StringVar(value="random (balanced)")
        ttk.Combobox(gen, textvariable=self.gen_vars["order"], state="readonly", width=16,
                     values=["random (balanced)", "in order (cycle)"]).grid(row=5, column=1, sticky="w")
        self.btn_fill = ttk.Button(gen, text="Replace the list", command=self.fill_list)
        self.btn_fill.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _ppi_editor(self, p):
        e = self.editor
        gen = ttk.LabelFrame(e, text="Session", padding=6)
        gen.grid(row=0, column=0, sticky="nw")
        self._field(gen, 0, 0, "Background noise (dB SPL)", ("background_noise_db",),
                    p.get("background_noise_db"), kind="opt_float")
        self._field(gen, 1, 0, "Habituation before first trial (s)", ("acclimation_s",), p["acclimation_s"])
        self._field(gen, 2, 0, "Record after last trial (s)", ("end_padding_s",), p["end_padding_s"])
        self._field(gen, 3, 0, "Time between trials, min (s)", ("iti_min_s",), p["iti_min_s"])
        self._field(gen, 4, 0, "Time between trials, max (s)", ("iti_max_s",), p["iti_max_s"])
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
        self._field(pu, 1, 0, "Frequency (kHz, tone only)", ("pulse", "freq_hz"), pp["freq_hz"], kind="khz")
        self._field(pu, 2, 0, "Level (dB SPL)", ("pulse", "level_db"), pp["level_db"])
        self._field(pu, 3, 0, "Rise (ms)", ("pulse", "rise_ms"), pp["rise_ms"])
        self._field(pu, 4, 0, "Plateau (ms)", ("pulse", "plateau_ms"), pp["plateau_ms"])
        self._field(pu, 5, 0, "Fall (ms)", ("pulse", "fall_ms"), pp["fall_ms"])

        pr = ttk.LabelFrame(e, text="Prepulse", padding=6)
        pr.grid(row=1, column=1, sticky="nw", padx=8, pady=6)
        q = p["prepulse"]
        self._field(pr, 0, 0, "Stimulus", ("prepulse", "stimulus"), q["stimulus"], kind="str",
                    values=["noise", "tone"])
        self._field(pr, 1, 0, "Frequency (kHz, tone only)", ("prepulse", "freq_hz"), q["freq_hz"], kind="khz")
        self._field(pr, 2, 0, "Levels above background (dB)", ("prepulse", "levels_above_bg_db"),
                    q["levels_above_bg_db"], kind="list", width=12)
        self._field(pr, 3, 0, "Rise (ms)", ("prepulse", "rise_ms"), q["rise_ms"])
        self._field(pr, 4, 0, "Plateau (ms)", ("prepulse", "plateau_ms"), q["plateau_ms"])
        self._field(pr, 5, 0, "Fall (ms)", ("prepulse", "fall_ms"), q["fall_ms"])
        self._field(pr, 6, 0, "Lead intervals, onset to onset (ms)", ("lead_intervals_ms",),
                    p["lead_intervals_ms"], kind="list", width=12)

        tr = ttk.LabelFrame(e, text="Trials", padding=6)
        tr.grid(row=1, column=0, sticky="nw", pady=6)
        self._field(tr, 0, 0, "Pulse-alone block at start", ("start_pulse_alone",), p["start_pulse_alone"], kind="int")
        self._field(tr, 1, 0, "Pulse-alone block at end", ("end_pulse_alone",), p["end_pulse_alone"], kind="int")
        self._field(tr, 2, 0, "Pulse-alone (mixed in)", ("n_pulse_alone",), p["n_pulse_alone"], kind="int")
        self._field(tr, 3, 0, "No-stimulus trials", ("n_no_stim",), p["n_no_stim"], kind="int")
        self._field(tr, 4, 0, "Prepulse+pulse, per level x lead", ("n_prepulse_pulse_each",),
                    p["n_prepulse_pulse_each"], kind="int")
        self._field(tr, 5, 0, "Prepulse-alone, per level", ("n_prepulse_alone_each",),
                    p["n_prepulse_alone_each"], kind="int")

    def _io_editor(self, p):
        e = self.editor
        gen = ttk.LabelFrame(e, text="Session", padding=6)
        gen.grid(row=0, column=0, sticky="nw")
        self._field(gen, 0, 0, "Background noise (dB SPL, blank = off)", ("background_noise_db",),
                    p.get("background_noise_db"), kind="opt_float")
        self._field(gen, 1, 0, "Habituation before first trial (s)", ("acclimation_s",), p["acclimation_s"])
        self._field(gen, 2, 0, "Time between trials (s)", ("iti_s",), p["iti_s"])
        self._field(gen, 3, 0, "Record after last trial (s)", ("end_padding_s",), p["end_padding_s"])
        self._field(gen, 4, 0, "Shuffle each block", ("randomize",), "yes" if p["randomize"] else "no",
                    kind="bool", values=["yes", "no"])
        self._field(gen, 5, 0, "Random seed (blank = new each run)", ("seed",), p.get("seed"), kind="opt_int")
        self._field(gen, 6, 0, "Assay variant (blank = plain startle)", ("assay_variant",),
                    p.get("assay_variant", ""), kind="str", width=18, values=protocols.ASSAY_VARIANTS)

        pu = ttk.LabelFrame(e, text="Startle sound", padding=6)
        pu.grid(row=0, column=1, sticky="nw", padx=8)
        pp = p["pulse"]
        self._field(pu, 0, 0, "Stimulus", ("pulse", "stimulus"), pp["stimulus"], kind="str",
                    values=["noise", "tone"])
        self._field(pu, 1, 0, "Frequency (kHz, tone only)", ("pulse", "freq_hz"), pp["freq_hz"], kind="khz")
        self._field(pu, 2, 0, "Rise (ms)", ("pulse", "rise_ms"), pp["rise_ms"])
        self._field(pu, 3, 0, "Plateau (ms)", ("pulse", "plateau_ms"), pp["plateau_ms"])
        self._field(pu, 4, 0, "Fall (ms)", ("pulse", "fall_ms"), pp["fall_ms"])

        tr = ttk.LabelFrame(e, text="Trials", padding=6)
        tr.grid(row=1, column=0, columnspan=2, sticky="nw", pady=6)
        self._field(tr, 0, 0, "Levels (dB SPL)", ("levels_db",), p["levels_db"], kind="list", width=22)
        self._field(tr, 1, 0, "Add a no-stimulus trial", ("include_no_stim",),
                    "yes" if p.get("include_no_stim") else "no", kind="bool", values=["yes", "no"])
        self._field(tr, 2, 0, "Blocks (each level once per block)", ("repeats",), p["repeats"], kind="int")

    def _show_edit_state(self):
        """Open or close the editing bar to match self.editing, and set the buttons."""
        self.btn_delete.configure(state="disabled" if self.builtin else "normal")
        self.btn_edit.configure(state="disabled" if self.editing else "normal")
        if self.editing:
            self.btn_save.pack(side="right")
            self.btn_cancel.pack(side="right", padx=(0, 6))
            self.editor.pack(fill="x", pady=(8, 0))
        else:
            self.btn_save.pack_forget()
            self.btn_cancel.pack_forget()
            self.editor.pack_forget()
        self.update_preview()

    def editor_protocol(self):
        """Protocol dict from the editor fields. Raises ValueError with a readable message."""
        p = copy.deepcopy(self.loaded)
        for path, (v, kind, w, label) in self.fields.items():
            s = v.get().strip()
            try:
                if kind == "float":
                    val = float(s)
                elif kind == "int":
                    val = int(s)
                elif kind == "khz":
                    val = float(s) * 1000
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
                raise ValueError(f"'{s}' isn't a valid value for {label}.")
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
                try:
                    trials.append(parse_list_line(line))
                except (ValueError, IndexError):
                    raise ValueError(f"Stimulus list line {n} should be 'time (s), kHz' or "
                                     f"'time (s), kHz, dB', with noise in place of the kHz "
                                     f"for white noise: {line}")
            p["trials"] = trials
        return p

    def fill_list(self):
        try:
            g = {k: v.get() for k, v in self.gen_vars.items()}
            first, n = float(g["first"]), int(g["n"])
            lo, hi = float(g["isi_min"]), float(g["isi_max"])
            freqs = [_gen_item(x) for x in g["freqs"].split(",") if x.strip()]
            if n < 1 or not freqs or lo <= 0 or hi < lo:
                raise ValueError
        except ValueError:
            messagebox.showerror("Fill the list", "Check the values (gap min must be more than 0 "
                                 "and no more than gap max).")
            return
        rng = np.random.default_rng()
        if g["order"].startswith("random"):
            seq = (freqs * (n // len(freqs) + 1))[:n]
            rng.shuffle(seq)
        else:
            seq = [freqs[i % len(freqs)] for i in range(n)]
        t, lines = first, []
        for f in seq:
            lines.append(f"{round(t, 3):g}, {f if f == 'noise' else format(f, 'g')}")
            t += rng.uniform(lo, hi)
        self.trials_text.delete("1.0", "end")
        self.trials_text.insert("end", "\n".join(lines))
        self.update_preview()

    # -- what will run: summary, timeline, trials ------------------------------
    def _on_text_modified(self, event=None):
        if self.trials_text is not None and self.trials_text.edit_modified():
            self.trials_text.edit_modified(False)
            self.schedule_preview()

    def schedule_preview(self):
        """Update the summary shortly after the last change (not on every keystroke)."""
        if self._preview_job is not None:
            self.parent.after_cancel(self._preview_job)
        self._preview_job = self.parent.after(PREVIEW_DELAY_MS, self.update_preview)

    def update_preview(self):
        self._preview_job = None
        if not self.loaded:
            return
        who = "Built-in" if self.builtin else "Your protocol"
        self.var_kind.set(f"{who} · {KINDS[self.loaded['type']][0]}")
        for w in self.facts.winfo_children():
            w.destroy()
        try:
            p = self.editor_protocol()
            self.trials, self.total_s = protocols.build_schedule(p)
            facts = protocols.summarize(p, self.trials, self.total_s)
            self.var_problem.set("")
        except Exception as e:
            p, self.trials, self.total_s = self.loaded, [], 0.0
            facts = []
            self.var_problem.set(f"Problem with this protocol: {e}")
        self.var_name.set(p["name"])
        for i, (label, value) in enumerate(facts):
            ttk.Label(self.facts, text=label, foreground="#555").grid(row=i, column=0, sticky="nw", pady=1)
            ttk.Label(self.facts, text=value, font=self._bold, wraplength=330, justify="left").grid(
                row=i, column=1, sticky="w", padx=(8, 0), pady=1)
        self.entry_reference.configure(state="normal")
        self.var_reference.set(p.get("reference", ""))
        self.entry_reference.configure(state="readonly")    # can be selected and copied, not changed
        self.table.delete(*self.table.get_children())
        for tr in self.trials:
            self.table.insert("", "end", values=(tr["trial"], f"{tr['ref_time_s']:.1f}",
                                                 protocols.TRIAL_TYPE_NAMES.get(tr["type"], tr["type"]),
                                                 protocols.trial_sound(tr)))
        if self.builtin:
            note = EDIT_BUILTIN_NOTE
        elif not self.editing:
            note = EDIT_HINT
        elif self.has_unsaved_changes():
            note = UNSAVED_NOTE
        else:
            note = EDITING_NOTE
        self.var_note.set(note)
        self.lbl_note.configure(foreground="#b00020" if note == UNSAVED_NOTE else "#555")
        self.draw_timeline()

    def draw_timeline(self):
        c = self.timeline
        c.delete("all")
        w, h = max(c.winfo_width(), TIMELINE_W), TIMELINE_H
        if not self.trials or self.total_s <= 0:
            c.create_text(w / 2, h / 2, text="No schedule to show", fill="#888")
            return
        x0, x1, y0, y1 = 38, w - 10, 12, h - 28
        levels = [tr[k]["level_db"] for tr in self.trials for k in ("pulse", "prepulse") if tr[k]]
        lo, hi = (min(levels), max(levels)) if levels else (60.0, 120.0)
        if hi - lo < 10:
            lo, hi = lo - 5, hi + 5
        X = lambda t: x0 + (x1 - x0) * t / self.total_s            # noqa: E731
        Y = lambda d: y1 - (y1 - y0) * (d - lo) / (hi - lo)         # noqa: E731
        first = self.trials[0]["ref_time_s"]
        if first > 0:
            c.create_rectangle(x0, y0, X(first), y1, fill="#eeeeee", outline="")
            if X(first) - x0 > 70:
                c.create_text((x0 + X(first)) / 2, (y0 + y1) / 2, text="habituation", fill="#777")
        c.create_line(x0, y1, x1, y1, fill="#999")
        c.create_line(x0, y0, x0, y1, fill="#999")
        for d, anchor_y in ((hi, y0), (lo, y1)):
            c.create_text(x0 - 4, anchor_y, text=f"{d:g}", anchor="e", fill="#555")
        c.create_text(x0 - 4, (y0 + y1) / 2, text="dB", anchor="e", fill="#555")
        c.create_text(x0, y1 + 4, text="0", anchor="n", fill="#555")
        c.create_text(x1, y1 + 4, text=f"{self.total_s / 60:.1f} min", anchor="ne", fill="#555")
        if X(first) - x0 > 40:
            c.create_text(X(first), y1 + 4, text=f"{first / 60:g} min", anchor="n", fill="#555")
        for tr in self.trials:
            x = X(tr["ref_time_s"])
            if tr["prepulse"]:
                y = Y(tr["prepulse"]["level_db"])
                c.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, outline="#1D9E75", tags="prepulse")
            if tr["pulse"]:
                y = Y(tr["pulse"]["level_db"])
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#534AB7", outline="", tags="pulse")
            if not tr["pulse"] and not tr["prepulse"]:
                c.create_line(x, y1 - 5, x, y1, fill="#999", tags="nostim")
        key = "dot = startle level"
        if any(tr["prepulse"] for tr in self.trials):
            key += ", ring = prepulse"
        if any(not tr["pulse"] and not tr["prepulse"] for tr in self.trials):
            key += ", tick = no stimulus"
        c.create_text((x0 + x1) / 2, h - 4, text=key, anchor="s", fill="#777")
