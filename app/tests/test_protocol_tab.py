"""The Protocol tab: summary card, timeline and trial list; Edit bar; New..., Copy..., Delete."""

import json
import tkinter as tk
import unittest
from unittest import mock

from boombox import protocol_tab, protocols
from tests.test_protocols_and_levels import protocol_dirs


class ProtocolTabTests(unittest.TestCase):
    def setUp(self):
        self.dirs = protocol_dirs()
        self.builtin_dir, self.user_dir = self.dirs.__enter__()
        protocols.ensure_builtin()
        self.root = tk.Tk()
        self.root.withdraw()
        self.var = tk.StringVar()
        self.names, self.logs, self.settings = [], [], {}
        frame = tk.Frame(self.root)
        self.tab = protocol_tab.ProtocolTab(frame, self.var, self.settings, self.logs.append,
                                            on_names=self.names.append, mono_font="Courier")

    def tearDown(self):
        self.root.destroy()
        self.dirs.__exit__(None, None, None)

    def select(self, name):
        self.tab.refresh(name)
        self.root.update()

    def field(self, *path):
        return self.tab.fields[path][0]

    def facts(self):
        labels = self.tab.facts.winfo_children()
        return {labels[i]["text"]: labels[i + 1]["text"] for i in range(0, len(labels), 2)}

    def new(self, name, kind="list"):
        with mock.patch.object(protocol_tab, "ask_new_protocol", return_value=(name, kind)):
            self.tab.new_protocol()

    def test_a_built_in_shows_what_it_runs(self):
        self.select(protocols.HEARING_NAME)
        self.assertEqual(self.tab.var_name.get(), protocols.HEARING_NAME)
        self.assertEqual(self.tab.var_kind.get(), "Built-in · Stimulus list")
        facts = self.facts()
        self.assertEqual(facts["Length"], "16.5 min")
        self.assertEqual(facts["Trials"], "44")
        self.assertEqual(facts["Startle levels"], "70–120 dB, 5 dB steps")
        self.assertEqual(facts["Background noise"], "65 dB, whole session")
        self.assertEqual(len(self.tab.table.get_children()), 44)
        self.assertEqual(self.tab.table.item(self.tab.table.get_children()[1])["values"][3], "8 kHz 75 dB")
        self.assertEqual(len(self.tab.timeline.find_withtag("pulse")), 44)
        self.assertFalse(self.tab.editing)
        self.assertFalse(self.tab.editor.winfo_manager())
        self.assertEqual(self.tab.var_note.get(), protocol_tab.EDIT_BUILTIN_NOTE)
        self.assertEqual(str(self.tab.btn_delete["state"]), "disabled")
        self.assertEqual(self.names[-1][:4], list(protocols.BUILTINS))
        self.assertEqual(self.settings["last_protocol"], protocols.HEARING_NAME)

    def test_the_reference_can_be_copied_but_not_changed(self):
        self.select(protocols.HEARING_NAME)
        ref = self.tab.entry_reference
        self.assertEqual(str(ref["state"]), "readonly")
        ref.selection_range(0, "end")
        self.assertIn("ucsf", ref.selection_get())

    def test_edit_on_a_built_in_offers_a_copy(self):
        self.select(protocols.HEARING_NAME)
        with mock.patch.object(protocol_tab.messagebox, "askyesno", return_value=False):
            self.tab.edit_protocol()
        self.assertFalse(self.tab.editing)
        with mock.patch.object(protocol_tab.messagebox, "askyesno", return_value=True), \
                mock.patch.object(protocol_tab.simpledialog, "askstring", return_value=" My hearing "):
            self.tab.edit_protocol()
        saved = json.loads((self.user_dir / "My_hearing.json").read_text())
        self.assertNotIn("builtin", saved)
        self.assertEqual(len(saved["trials"]), 44)
        self.assertEqual(self.var.get(), "My hearing")
        self.assertTrue(self.tab.editing)
        self.assertEqual(self.tab.var_kind.get(), "Your protocol · Stimulus list")

    def test_copy_and_new_refuse_a_name_already_used(self):
        before = (self.user_dir / "PPI_Default.json").read_text()
        self.select(protocols.TVS_NAME)
        with mock.patch.object(protocol_tab.simpledialog, "askstring", return_value="PPI Default"), \
                mock.patch.object(protocol_tab.messagebox, "showerror") as shown:
            self.tab.copy_protocol()
        shown.assert_called_once()
        with mock.patch.object(protocol_tab, "ask_new_protocol", return_value=("PPI Default", "list")), \
                mock.patch.object(protocol_tab.messagebox, "showerror") as shown:
            self.tab.new_protocol()
        shown.assert_called_once()
        self.assertEqual((self.user_dir / "PPI_Default.json").read_text(), before)
        self.assertEqual(self.var.get(), protocols.TVS_NAME)

    def test_new_offers_all_three_kinds_and_opens_the_editor(self):
        for name, kind in (("My list", "list"), ("My PPI", "ppi"), ("My IO", "io")):
            self.new(name, kind)
            p = protocols.load(name)
            self.assertEqual(p["type"], kind)
            self.assertNotIn("builtin", p)
            self.assertEqual(self.var.get(), name)
            self.assertTrue(self.tab.editing)
        self.assertEqual(protocols.load("My IO")["reference"], "")

    def test_edit_then_save(self):
        self.select("PPI Default")
        self.assertEqual(self.tab.var_note.get(), protocol_tab.EDIT_HINT)
        self.tab.edit_protocol()
        self.root.update()
        self.assertTrue(self.tab.editor.winfo_manager())
        self.assertEqual(self.tab.var_note.get(), protocol_tab.EDITING_NOTE)
        self.field("pulse", "level_db").set("110")
        self.tab.update_preview()
        self.assertEqual(self.tab.var_note.get(), protocol_tab.UNSAVED_NOTE)
        self.tab.save_protocol()
        self.assertEqual(protocols.load("PPI Default")["pulse"]["level_db"], 110.0)
        self.assertFalse(self.tab.editing)
        self.assertEqual(self.tab.var_note.get(), protocol_tab.EDIT_HINT)

    def test_cancel_discards_changes(self):
        self.select("PPI Default")
        self.tab.edit_protocol()
        self.field("pulse", "level_db").set("110")
        with mock.patch.object(protocol_tab.messagebox, "askyesno", return_value=True):
            self.tab.cancel_edit()
        self.assertFalse(self.tab.editing)
        self.assertEqual(self.field("pulse", "level_db").get(), "105")
        self.assertEqual(protocols.load("PPI Default")["pulse"]["level_db"], 105.0)

    def test_switching_away_from_unsaved_changes_asks_first(self):
        self.select("PPI Default")
        self.tab.edit_protocol()
        self.field("pulse", "level_db").set("110")
        self.var.set(protocols.TVS_NAME)
        with mock.patch.object(protocol_tab.messagebox, "askyesno", return_value=False) as asked:
            self.tab.on_selected()
        asked.assert_called_once()
        self.assertEqual(self.var.get(), "PPI Default")
        self.assertEqual(self.field("pulse", "level_db").get(), "110")

    def test_ppi_frequencies_are_in_khz_and_the_timeline_shows_prepulses(self):
        self.select("PPI Default")
        self.assertEqual(self.field("pulse", "freq_hz").get(), "8")
        self.field("pulse", "freq_hz").set("12")
        self.assertEqual(self.tab.editor_protocol()["pulse"]["freq_hz"], 12000.0)
        self.tab.update_preview()
        self.assertEqual(len(self.tab.timeline.find_withtag("prepulse")), 30)
        self.assertEqual(len(self.tab.timeline.find_withtag("nostim")), 10)

    def test_trials_follow_the_list_and_bad_values_name_their_field(self):
        self.new("Mine")
        self.tab.gen_vars["n"].set("4")
        self.tab.fill_list()
        lines = self.tab.trials_text.get("1.0", "end").strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(len(self.tab.table.get_children()), 4)
        self.assertEqual(self.facts()["Trials"], "4")
        self.field("startle", "level_db").set("loud")
        self.tab.update_preview()
        self.assertEqual(len(self.tab.table.get_children()), 0)
        self.assertIn("'loud' isn't a valid value for Level (dB SPL)", self.tab.var_problem.get())

    def test_delete_removes_your_protocol(self):
        self.new("Gone soon")
        with mock.patch.object(protocol_tab.messagebox, "askyesno", return_value=True):
            self.tab.delete_protocol()
        self.assertNotIn("Gone soon", protocols.list_protocols())
        self.assertEqual(self.var.get(), protocols.TVS_NAME)


class SummaryTests(unittest.TestCase):
    def summary(self, p):
        trials, total = protocols.build_schedule(p)
        return dict(protocols.summarize(p, trials, total))

    def test_builtins_are_described_in_plain_words(self):
        tvs = self.summary(protocols.BUILTINS[protocols.TVS_NAME])
        self.assertEqual(tvs["Startle sound"], "4, 8, 12, 16 and 20 kHz tones, 10 ms")
        self.assertEqual(tvs["Startle levels"], "105 dB")
        self.assertEqual(tvs["Time between trials"], "12–43 s (varies)")
        io = self.summary(protocols.BUILTINS[protocols.IO_NAME])
        self.assertEqual(io["Trial types"], "30 startle, 5 no stimulus")
        self.assertEqual(io["Startle sound"], "white-noise bursts, 40 ms")
        self.assertEqual(io["Startle levels"], "70–120 dB, 10 dB steps")
        ppi = self.summary(protocols.DEFAULT_PPI)
        self.assertEqual(ppi["Prepulse levels"], "68, 71, 77 dB")
        self.assertEqual(ppi["Lead intervals"], "100 ms")
        self.assertEqual(ppi["Assay variant"], "Prepulse Inhibition")

    def test_a_mixed_list_and_no_background_noise(self):
        p = dict(protocols.DEFAULT_LIST, background_noise_db=None,
                 trials=[{"time_s": 300, "stimulus": "noise"}, {"time_s": 330, "freq_hz": 8000}])
        s = self.summary(p)
        self.assertEqual(s["Startle sound"], "8 kHz tone and white-noise bursts, 10 ms")
        self.assertEqual(s["Background noise"], "off")
        self.assertEqual(s["Time between trials"], "30 s")


if __name__ == "__main__":
    unittest.main()
