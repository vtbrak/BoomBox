"""The clap test window (opened from the Settings tab): measures the camera latency."""

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import claptest

VIEW_W = 640
INTRO = ("This measures how late the camera's pictures arrive, using claps: the microphone "
         "hears each clap and the camera sees it at the same moment.\n\n"
         "1. Hold your hands where the camera can see them, close to the microphone.\n"
         "2. Press Record and clap about 8 times, a second or two apart. Keep your hands "
         "together for a moment after each clap.\n"
         "3. For each clap, step through the pictures to the FIRST one where your hands touch.")


class ClapWindow:
    def __init__(self, app):
        self.app = app
        self.rec = None             # the recording in progress or being reviewed
        self.results = []           # latency (ms) for each clap marked so far
        self.clap = 0               # which clap is being reviewed
        self.frame = 0              # which frame is shown
        self._photo = None
        self._tick = None

        self.win = win = tk.Toplevel(app.root)
        win.title("Clap test: camera latency")
        win.transient(app.root)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Left>", lambda e: self.step(-1))
        win.bind("<Right>", lambda e: self.step(1))

        pad = ttk.Frame(win, padding=12)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text=INTRO, wraplength=VIEW_W, justify="left").pack(anchor="w")

        top = ttk.Frame(pad)
        top.pack(fill="x", pady=(10, 4))
        self.btn_record = ttk.Button(top, text=f"Record ({claptest.RECORD_S} s)", command=self.record)
        self.btn_record.pack(side="left")
        self.var_status = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.var_status).pack(side="left", padx=10)

        self.picture = ttk.Label(pad)
        self.picture.pack(pady=6)
        self.var_frame = tk.StringVar(value="")
        ttk.Label(pad, textvariable=self.var_frame).pack()

        nav = ttk.Frame(pad)
        nav.pack(pady=6)
        self.btn_prev = ttk.Button(nav, text="◀ Previous picture", command=lambda: self.step(-1))
        self.btn_next = ttk.Button(nav, text="Next picture ▶", command=lambda: self.step(1))
        self.btn_mark = ttk.Button(nav, text="Hands first touch here", command=self.mark)
        self.btn_skip = ttk.Button(nav, text="Skip this clap", command=self.next_clap)
        for b in (self.btn_prev, self.btn_next, self.btn_mark, self.btn_skip):
            b.pack(side="left", padx=4)

        self.var_result = tk.StringVar(value="")
        ttk.Label(pad, textvariable=self.var_result, wraplength=VIEW_W, justify="left").pack(
            anchor="w", pady=(8, 4))
        bottom = ttk.Frame(pad)
        bottom.pack(fill="x")
        self.btn_use = ttk.Button(bottom, text="Use this latency", command=self.use)
        self.btn_use.pack(side="left")
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")

        self._show_blank()
        self._review_buttons(False)
        self.btn_use.state(["disabled"])
        win.grab_set()              # nothing else (such as a session) can start meanwhile

    # -- recording ----------------------------------------------------------
    def record(self):
        app = self.app
        cam = app.camera
        if cam is None or cam.frame_count == 0:
            messagebox.showerror("Clap test", "The camera isn't running. Start it on the Camera tab.",
                                 parent=self.win)
            return
        mic = app.settings.get("mic_device")
        if not mic:
            messagebox.showerror("Clap test", "Choose a microphone on the Settings tab, press "
                                 "\"Save settings and restart audio\", then try again.", parent=self.win)
            return
        try:
            self.rec = claptest.ClapRecording(cam, mic)
            self.rec.start()
        except Exception as e:
            self.rec = None
            messagebox.showerror("Clap test", f"Could not start the microphone:\n{e}", parent=self.win)
            return
        self.results = []
        self.var_result.set("")
        self.btn_use.state(["disabled"])
        self.btn_record.state(["disabled"])
        self._review_buttons(False)
        self._show_blank()
        self._countdown()

    def _countdown(self):
        left = self.rec.remaining()
        if left > 0:
            self.var_status.set(f"Recording: clap now.  {left:.0f} s left")
            self._tick = self.win.after(200, self._countdown)
            return
        self._tick = None
        self.btn_record.state(["!disabled"])
        try:
            n = self.rec.finish()
        except Exception as e:
            self.rec = None
            self.var_status.set("Ready.")
            messagebox.showerror("Clap test", f"Could not read the recording:\n{e}", parent=self.win)
            return
        if n == 0:
            self.rec = None
            self.var_status.set("No claps heard. Clap louder or closer to the microphone, then record again.")
            return
        self.clap = -1
        self.next_clap()

    # -- review ---------------------------------------------------------------
    def _review_buttons(self, on):
        for b in (self.btn_prev, self.btn_next, self.btn_mark, self.btn_skip):
            b.state(["!disabled"] if on else ["disabled"])

    def next_clap(self):
        self.clap += 1
        if self.clap >= len(self.rec.clap_times):
            self._finished()
            return
        self.frame = self.rec.frames.index_at(self.rec.clap_times[self.clap])
        self._review_buttons(True)
        self._show()

    def step(self, d):
        if self.rec is None or "disabled" in self.btn_mark.state():
            return
        self.frame = min(max(self.frame + d, 0), len(self.rec.frames.frames) - 1)
        self._show()

    def _show(self):
        fr = self.rec.frames
        img = Image.fromarray(fr.frames[self.frame])
        img = img.resize((VIEW_W, max(1, round(VIEW_W * img.height / img.width))))
        self._photo = ImageTk.PhotoImage(img)
        self.picture.configure(image=self._photo)
        after = (fr.times[self.frame] - self.rec.clap_times[self.clap]) * 1000
        self.var_status.set(f"Clap {self.clap + 1} of {len(self.rec.clap_times)}")
        self.var_frame.set(f"This picture arrived {after:+.0f} ms from the clap sound.  "
                           "Arrow keys also step.")

    def _show_blank(self):
        self._photo = ImageTk.PhotoImage(Image.new("L", (VIEW_W, VIEW_W * 9 // 16), 40))
        self.picture.configure(image=self._photo)
        self.var_frame.set("")

    def mark(self):
        fr = self.rec.frames
        self.results.append(claptest.latency_ms(fr.times[self.frame], self.rec.clap_times[self.clap],
                                                self.rec.cam.fps))
        self._report()
        self.next_clap()

    def _report(self):
        mean, sd, n = claptest.summarize(self.results)
        if n:
            self.var_result.set(f"Camera latency: {mean:.0f} ms  (from {n} clap{'s' if n != 1 else ''}"
                                + (f", spread ±{sd:.0f} ms" if n > 1 else "") + ")")

    def _finished(self):
        self._review_buttons(False)
        mean, sd, n = claptest.summarize(self.results)
        if n == 0:
            self.var_status.set("No claps marked. Record again.")
            return
        self.var_status.set("Done.")
        note = ""
        if n < 5:
            note = "  Fewer than 5 claps: record again for a steadier value."
        elif mean < 0:
            note = "  A value below 0 isn't possible; check that the right picture was chosen."
        self.var_result.set(self.var_result.get() + note)
        self.btn_use.state(["!disabled"])

    # -- result -----------------------------------------------------------------
    def use(self):
        mean, _, n = claptest.summarize(self.results)
        if not n:
            return
        value = round(max(mean, 0.0), 1)
        self.app.set_camera_latency(value)
        self.var_status.set(f"Camera latency set to {value:g} ms and saved.")
        self.btn_use.state(["disabled"])

    def close(self):
        if self._tick is not None:
            self.win.after_cancel(self._tick)
            self._tick = None
            try:
                self.rec.cancel()
            except Exception:
                pass
        self.win.grab_release()
        self.win.destroy()
