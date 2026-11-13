# Boom Box

Records acoustic startle response (ASR) and prepulse inhibition (PPI) sessions in mice on a Mac or
Windows PC (Windows support is new and still being tested):
grayscale video from a USB camera, raised-cosine tone bursts through the headphone jack
(to an amplifier and speaker), constant background white noise, and a microphone track used to
check sync. Every stimulus is logged with the video frame it occurred in.

## What's in the folder

| File or folder | What it's for |
|---|---|
| `Boom_Box.command` / `Boom_Box.bat` | Start Boom Box (Mac / Windows) |
| `Install_BoomBox.command` / `Install_BoomBox.bat` | Install Boom Box, or update it after downloading a new version (Mac / Windows) |
| `README.md`, `INSTALL.md` | This file and the install guide |
| `Data` | Your recordings (appears after the first session) |
| `app` | The program itself: code, built-in protocols, tests and the Track Tamer data guide (`app/docs`). Everything you set up (settings, calibration, experimenter names, your own protocols) is in `app/config`, the one folder to copy when updating. You don't need to open it |

## Installing

Everything about installing is in **[INSTALL.md](INSTALL.md)**:

- [Quick install](INSTALL.md#quick-install): three steps for a Mac that already has Anaconda
- [Full step-by-step install](INSTALL.md#step-1-check-which-kind-of-mac-you-have): Anaconda, downloading the program, permissions, first-time settings
- [No password method](INSTALL.md#no-password-method): install and start from Terminal (`bash` + drag the file) when macOS asks for an administrator password
- [Installing a newer version](INSTALL.md#installing-a-newer-version-later): update without losing calibration, settings or data
- [Troubleshooting](INSTALL.md#troubleshooting)
- [Installing on Windows](INSTALL.md#installing-on-windows): Anaconda, setup with `Install_BoomBox.bat`, and first-time settings on a PC

## Starting the program each time

**On Windows:** double-click **`Boom_Box.bat`** and keep the black window open while the program runs.
You don't need to open Anaconda or rerun the setup. The rest of this section is for Macs.

After the first-time setup, use either method below. That includes after closing the program, logging
out, or restarting the Mac. **You never need to open Anaconda or run `Install_BoomBox.command` again**;
`Boom_Box.command` switches on the program's environment by itself every time.

**Method 1: Double-click**
- Double-click **`Boom_Box.command`** in the BoomBox folder (or its Dock icon, if you added one).
- Important:
  - If macOS asks for an **administrator password**, cancel and use Method 2 instead.
  - A Terminal window opens first. **Leave it open**; closing it quits the program.

**Method 2: Terminal (no password)**
- Open **Terminal** (⌘ + Space, type *Terminal*, press Return).
- Type `bash`, a space, then **drag `Boom_Box.command`** from the BoomBox folder into the window and press Return.
- Important:
  - Put a **space after `bash`** before dragging the file in.
  - Drag the **file** `Boom_Box.command`, not the BoomBox folder ("is a directory" means the folder was dragged).
  - "No such file or directory" means the space was missing or the file was moved; try again.
  - **Leave the Terminal window open** while the program runs.
  - The first-time installer runs the same way: `bash`, a space, drag in `Install_BoomBox.command`.

**Both methods**
- Plug in the camera, USB microphone and amplifier **before** starting. If you plug the camera in later,
  click **Refresh list** on the Camera tab, then **Apply / restart camera**.
- Close the program with its own window (the red button). Saved settings, calibration and experimenter
  names are kept for next time.
- Only run `Install_BoomBox.command` again after installing a newer version of the program, or if
  the program stops starting because something is missing.

## Before each day

- Plug the amplifier into the headphone jack. In **Settings**, choose *External Headphones* as the
  sound output and the USB microphone.
- Keep the Mac volume at the value used for calibration (the program warns if it changed).
- Turn on **Do Not Disturb** so notification sounds can't startle the animal.

## Calibration (Calibration tab)

Put a sound level meter where the mouse's head will be. For each frequency (and the white noise),
press **Play**, read the meter, and type the reading into *Measured dB SPL*. Press **Save calibration**.
The program then plays every stimulus at the dB SPL in the protocol, with one gain per frequency so
all frequencies are equally loud. Tones are calibrated by peak level, so a 10 ms burst has the same
peak as the continuous calibration tone. You can add other frequencies with *Add frequency*.

Until calibrated, levels are approximate and every log is marked `uncalibrated`.
"Loudest possible" shows the maximum each frequency can reach; if a protocol asks for more, the
session won't start (turn up the amplifier and recalibrate).

**Check selected protocol** opens a window that answers whether the protocol on the Session and
Protocol tabs can be played at its levels:

- At the top, one verdict: *Ready*, *Not calibrated*, *Some sounds aren't calibrated*, or *N levels
  are louder than the speaker can play*, with what to do about it.
- Under it, when the calibration was made, at what volume, and which sounds were measured.
- One row per sound (each tone frequency, white-noise bursts, prepulses, background noise): its
  levels, whether it was *measured*, *estimated* (between measured frequencies) or *not measured*,
  and how much room is left at its loudest level ("12 dB to spare" or "120 dB is 3 dB too loud").
- *Show output levels (dBFS)* lists the exact output for every level.

The same check runs when a session starts, with one line per sound that has a problem.

**Speaker limit:** the 12, 16 and 20 kHz rows show a warning. The lab speaker can blow out above
100 dB at those frequencies, so keep them at or below 100 dB.

## Camera (Camera tab)

Default is **1280x720 at 30 fps**; 60 and 90 fps can be selected if the camera supports them
(*Show camera modes* lists what it supports). Adjust exposure, gain, focus etc. while watching the
preview, then tick **Lock camera settings**. Locked values are saved and re-applied at every session.
Turn auto exposure off and keep the exposure shorter than one frame (33 ms at 30 fps, 11 ms at 90 fps).

Before version 1.3.4, Macs recorded 1280x720 video at only 10 fps (the camera's slow uncompressed
mode). Boom Box repeated frames to keep the MP4 at 30 fps, so those recordings show about two
repeated frames out of every three. Each repeat is marked in the `_frames.csv`.

*Camera latency (ms)* is subtracted from each frame's arrival time. Leave it at 0 unless you
measure it. To measure it, use **Clap test...** on the Settings tab (it needs the microphone):
press Record, clap about 8 times in view of the camera and close to the microphone, then for each
clap step to the first picture where your hands touch. The window averages the claps and
**Use this latency** saves the value. Measure at the resolution and frame rate you record with.

## Protocols (Protocol tab)

Every protocol starts with a **5-minute habituation** in 65 dB background white noise, and the noise
keeps playing through every stimulus until the session ends. All tones are
10 ms bursts with a raised-cosine envelope (5 ms rise, 5 ms fall, no plateau).

The Protocol tab shows what a protocol will run before anything else:

- **Summary** (left): the protocol's name and kind (*Stimulus list*, *Prepulse inhibition (PPI)* or
  *Input/output curve (I/O)*), then its length, number of trials, first trial, time between trials,
  startle sound and levels, prepulses (PPI), background noise and assay variant. The **Reference**
  link can be selected and copied.
- **Timeline** (left): the whole session at a glance, with one dot per startle placed by time and
  level, rings for prepulses and ticks for no-stimulus trials. The grey area is the habituation.
- **Trials** (right): every trial in order, with its time, type and sound.

The row at the top:

- **Protocol** menu: the protocol to look at. It's the same choice as on the Session tab.
- **New...**: makes a protocol. Give it a name and pick its kind; it opens ready to edit.
- **Copy...**: saves the protocol under a new name and opens the copy ready to edit. This is how to
  change a built-in protocol.
- **Edit**: opens the editing bar under the timeline, with the settings and, for a stimulus list,
  the list itself. The summary, timeline and trials follow your changes as you type. **Save** keeps
  them; **Cancel** throws them away. Until you save, sessions use the saved version, and Boom Box
  asks before you switch away from unsaved changes.
- **Delete**: deletes one of your protocols.

Four protocols are built in. They can't be changed or deleted; **Edit** on a built-in offers to make
your own copy.

- **Tone Volume Sensitivity** (formerly "ASR Standard"): 15 tones at 105 dB. Frequencies 12, 4, 16,
  20, 8, 4, 20, 16, 12, 8, 8, 16, 4, 20, 12 kHz at 300, 337, 365, 398, 428, 440, 471, 514, 533, 568,
  599, 638, 666, 695 and 710 s. That's the published series (first tone at 120 s), shifted so the
  first tone comes right after the habituation. From https://doi.org/10.1016/j.jneumeth.2025.110497.
- **Startle Habituation**: 100 tones at 8 kHz and 115 dB, one every 15 s from 300 s. Recorded with
  the `Startle Habituation` assay variant. The habituation design is from
  https://doi.org/10.3389/fnint.2013.00103; the 8 kHz frequency and 115 dB level
  were chosen from https://doi.org/10.1016/j.jneumeth.2025.110497.
- **Hearing Test**: 8 kHz tones from 70 to 120 dB in 5 dB steps (70, 75, 80 … 120), in two ascending
  and two descending series (ascending, descending, ascending, descending), one every 15 s from
  315 s: 44 tones. The 65 dB background noise stays on throughout, so the series starts at 70 dB
  (quieter tones would be masked). Before 1.3.10 the noise turned off at 300 s and the tones went
  from 40 to 120 dB in 10 dB steps.
  From the UCSF IACUC standard procedure, https://iacuc.ucsf.edu/content/acoustic-startle-response.
- **I/O** (input/output curve): 40 ms white-noise bursts at 70, 80, 90, 100, 110 and 120 dB plus a
  no-stimulus trial, in five blocks, each with all seven in a new random order, one every 15 s from
  300 s: 35 trials, with the 65 dB background noise throughout. From
  https://doi.org/10.1523/JNEUROSCI.1313-25.2026. Note that a 120 dB noise burst needs more speaker
  output than a 120 dB tone; the Calibration tab's *Check selected protocol* shows whether it's reachable.

Every protocol has a **Reference** field for the paper its design comes from; it's saved with each
session (in the info file and the event log).

Your own protocols:
- **Stimulus list**: any times and frequencies. Each line is `time (s), kHz`, with an optional third
  value for that stimulus's dB; lines without one use the *Default startle tone* level. For a
  **white-noise burst** instead of a tone, write `noise` in place of the kHz (e.g. `300, noise, 110`);
  one list can mix tones and noise. Noise uses the white noise calibration. *Fill the list
  automatically* writes a new list (fixed or random gaps; its *Frequencies* box accepts `noise` too)
  and **Replace the list** puts it in place of the current one.
- **Prepulse inhibition (PPI)**: pulse and prepulse stimuli, prepulse levels above background, lead
  intervals, trial counts, pulse-alone blocks, random times between trials. Frequencies are in kHz.
- **Input/output curve (I/O)**: startle bursts at a list of levels, each level once per block, in
  shuffled blocks, with an optional no-stimulus trial in each block.

## Running a session (Session tab)

1. Choose the experimenter (*Add a name* the first time), enter the Animal ID and other details
   (sex F/M/U, strain, date of birth, cohort / litter, treatment, trial day, session number),
   choose the protocol.
2. Optionally press **Start background noise** for acclimation before recording.
3. **START SESSION**: a checklist of warnings appears, then a 5 s countdown. Frame 0 of the video is
   t = 0 for every time in the logs.
4. The session ends by itself after the last stimulus plus the protocol's padding (default 30 s).
   **STOP** ends early and still saves everything.
5. **Next animal** clears the animal fields and keeps everything else.

## Output files

Files follow the **Track Tamer video metadata standard** (schema 1), so Track Tamer can read each
session's information automatically. Each session gets a folder
`Data/<date>_<time>_<arena>_<AnimalID>/`, and its files start with `<date>_<time>_<arena>`
(e.g. `2026-11-06_15-30-00_ASR1`). The arena (`ASR1`) and camera label (`Side`) are set once per rig
on the **Settings** tab, using letters, digits and `-` only.

| File | Contents |
|---|---|
| `…_ASR1_Side.mp4` | Grayscale H.264 video with the microphone as its audio track |
| `…_ASR1_info.json` | **Trial information for Track Tamer:** date, start time, assay (`Acoustic Startle Response`) and variant, arena, room, experimenter, animal details, session length, the camera entry (video name, frame counts, repeated frames, all camera settings) and the `stimuli` list. Boom Box's own details (protocol, schedule, per-trial timing, calibration, audio settings) are inside its `boom_box` section. |
| `…_ASR1_Side_frames.csv` | Measured time of every video frame: `frame`, `video_time_s`, `repeated` (true for frames repeated because the camera dropped one). This is the record of timing. |
| `…_ASR1_trials.csv` | Boom Box's detail, one row per trial: scheduled and actual times (ms), video frame, frequency, level, dBFS, calibration status, mic-measured onset and frame |
| `…_ASR1_Side_audio.wav` | Microphone audio, aligned so sample 0 = video frame 0 (full bandwidth) |
| `…_ASR1_events.log` | Readable timeline |

The **running log** `Data/Data_log.csv` (named after the data folder) gets one row per session: date,
animal, experimenter, session length, frames, video name and so on. Every column is always there,
blank when there's nothing to put in it. The columns, their order and their words (`yes`/`no` for
`stopped_early`) are the same as in the other lab apps' logs. If the log is open in Excel on Windows,
the row waits in `Data_log_pending.csv` and is added next time. (Before 1.3.5 each session had an
`_info.csv` instead.)

Frames are numbered from 0. In the trials file, times are in milliseconds from the start of frame 0;
in the info and frames files they're in seconds. `pulse_frame` is the frame being exposed when the
sound left the computer; `pulse_mic_frame` is the frame when the microphone heard it.

**Assay variant:** set per protocol on the Protocol tab: blank for a plain startle session,
`Prepulse Inhibition` (the default for PPI protocols) or `Startle Habituation`.

## Timing notes

- Stimuli are placed sample-accurately using the audio hardware clock (typically within 0.1 ms of
  schedule; `late_ms` reports any delay).
- If the camera drops frames, the previous frame is repeated so the MP4 stays at a constant rate in
  step with real time, and each repeat is logged.
- On a Mac, a camera that runs slightly faster than its set rate loses about one frame in 100: macOS
  discards the extra frames before Boom Box receives them. The lab camera does this (its 30 fps is
  really 30.3). These show up as double-length gaps in `_frames.csv`.
- The video is compressed with x264 intra-refresh, so there's no keyframe every 250 frames. Before
  1.3.9 each keyframe showed up as a burst of camera grain that motion tracking could read as
  movement.
- At 30 fps a frame lasts 33 ms, longer than the 10 ms tone; use 60/90 fps for finer timing.
