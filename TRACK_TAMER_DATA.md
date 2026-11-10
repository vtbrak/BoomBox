# Boom Box data for Track Tamer

What Boom Box saves beside each video, and how to read it. This describes
**Boom Box 1.3.1**, writing **schema 1** of the Track Tamer video metadata
standard (draft). It adds Boom Box's specifics to that standard and doesn't
replace it.

**Assay:** every Boom Box session is `Acoustic Startle Response`.

---

## 1. Quick summary

- Read **`_info.json`**: it has the trial details and the list of stimuli.
- Take frame times from **`_frames.csv`**, not from frame number ÷ frame rate.
- Find each startle in **`stimuli`**, and ignore repeated frames when looking
  for movement peaks.
- To analyze by tone frequency, use **`pulse_freq_hz`** in `stimuli`.
- Check `boom_box.calibrated`. If it's `false`, the dB values are only
  approximate.

---

## 2. Files in a session

Each session has its own folder. Every file name starts with
`<date>_<time>_<arena>`, e.g. `2026-11-09_15-01-02_ASR1`. Below, `Side` is the
camera label and `ASR1` is the arena; both are set per rig.

| File | Track Tamer should | What it is |
|---|---|---|
| `…_ASR1_Side.mp4` | **track this** | The video |
| `…_ASR1_info.json` | **read this** | Trial information, stimuli, and Boom Box's details |
| `…_ASR1_Side_frames.csv` | **read this** | Measured time of every frame |
| `…_ASR1_info.csv` | skip | The JSON's top-level fields as one row, for people. Columns vary, because empty fields are left out |
| `…_ASR1_trials.csv` | optional | Per-trial detail; the same data as `boom_box.trials` |
| `…_ASR1_Side_audio.wav` | skip | Microphone recording, aligned to the video. Only there if a mic was selected |
| `…_ASR1_events.log` | skip | Readable timeline, for people |

Don't work out the start time from the **folder name**. It's set just before
recording starts and can differ from the file names by a second or so. Use
`date` and `start_time`.

---

## 3. Conventions

- **Time zero** is the start of video frame 0.
- **Frames** count from 0, matching the frames in the MP4.
- **Units:** seconds in `stimuli` and `_frames.csv`; milliseconds in
  `_trials.csv` and `boom_box.trials`.
- **Missing values:** in the standard fields, an unknown or empty value is left
  out. Inside `boom_box` it may be `""` or `null`.
- **`sex`** is always written, as `F`, `M` or `U`.

---

## 4. Standard fields in `_info.json`

| Field | How Boom Box fills it |
|---|---|
| `schema_version` | `1` |
| `app_name`, `app_version` | `Boom Box`, e.g. `1.3.1` |
| `date`, `start_time` | The computer's clock at video frame 0 |
| `assay` | Always `Acoustic Startle Response` |
| `assay_variant` | Set per protocol: `Prepulse Inhibition`, `Startle Habituation`, or left out for plain startle |
| `arena`, `room` | From Boom Box's Settings tab |
| `experimenter`, `animal_id`, `sex`, `strain`, `dob`, `cohort`, `treatment`, `trial_day`, `session_number`, `notes` | Typed in for each session; left out if blank (except `sex`) |
| `duration_set_min` | The protocol's full planned length, including any time before the first stimulus and after the last one |
| `duration_actual_s` | Frames written ÷ frame rate |
| `stopped_early` | `true` if the user stopped the session or the camera failed |

`phase` is never written, since this assay has no phase list.

### `cameras`: always one entry

| Field | How Boom Box fills it |
|---|---|
| `label` | Camera label from Settings, e.g. `Side` |
| `camera_position` | The camera's device name. Boom Box has no camera positions |
| `video`, `timestamps_csv` | File names in this folder |
| `fps_set` | Frame rate requested: 30, 60 or 90 |
| `fps_measured` | Calculated from the first and last frame times |
| `width_px`, `height_px` | Frame size |
| `frames` | Frames written, including repeats |
| `verified_frames_in_file` | Frames counted in the finished MP4. Should equal `frames`; left out if it couldn't be counted |
| `repeated_frames` | How many frames were repeated |
| `repeated_frame_indices` | Which frames; left out when there are none |
| `error` | Only present if the camera reported an error |
| `camera_settings` | See below |

**`camera_settings`** holds `encoder` (`libx264`), `crf`, `encoder_preset`,
`pixel_format` (`yuv420p`), `color` (`grayscale`), `width_px`, `height_px`,
`fps`, `camera_latency_ms`, `controls_locked` and `controls`.

The video is grayscale but stored as `yuv420p`, so a decoder may return three
identical color channels.

`controls` holds the camera's values at the start of the session. Its contents
depend on the computer:

| Computer | Names in `controls` |
|---|---|
| Mac | `auto_exposure`, `exposure_priority`, `exposure_time` (units of 0.1 ms), `auto_focus`, `focus`, `gain`, `brightness`, `contrast`, `gamma`, `sharpness`, `backlight`, `auto_white_balance`, `white_balance`, `power_line` |
| Windows | `auto_exposure`, `autofocus`, `exposure`, `gain`, `focus`, `brightness`, `contrast`, `gamma`, `sharpness`, `white_balance`, as reported by the camera driver. Units depend on the camera |

A camera only reports the controls it has, so some may be missing. Treat these
values as a record of the settings; don't calculate from them.

Each camera entry also has a `boom_box` object:

| Field | Meaning |
|---|---|
| `gaps` | Each place the camera dropped frames: `frame` (first repeated frame), `time_s` (when the camera resumed), `missing` (how many) |
| `discarded_camera_frames` | Frames thrown away because the camera ran ahead of the set rate. They aren't in the video |
| `max_encoder_queue` | Diagnostic only |

---

## 5. `_frames.csv`: frame timing

One row per video frame, in order.

| Column | Meaning |
|---|---|
| `frame` | Frame number, from 0 |
| `video_time_s` | Seconds from frame 0 |
| `repeated` | `true` if this frame is a copy of the previous one |

- For a normal frame, the time is when the frame **reached the computer**, minus
  `camera_latency_ms`.
- For a repeated frame, the time is a calculated slot (frame number ÷ frame
  rate), not a measurement, and the picture is a copy of the last real frame.
  **Leave repeated frames out of movement and speed peaks.** A repeat shows no
  movement, and the next real frame shows all the movement across the gap.
- Boom Box keeps the video within about 1.5 frames of real time, so frame number
  ÷ frame rate is close but not exact. `video_time_s` is the record of timing.

---

## 6. `stimuli`: the startle events

One entry per trial that took place, in order. Left out entirely if no trial
took place.

| Field | Meaning |
|---|---|
| `frame` | Video frame at the event time |
| `video_time_s` | Event time, in seconds from frame 0 |
| `type` | `pulse`, `prepulse+pulse`, `prepulse` or `none` |
| `pulse_db` | Pulse level in dB SPL. Only when there's a pulse |
| `pulse_stimulus` | `tone` or `noise`. Only when there's a pulse |
| `pulse_freq_hz` | Tone frequency of the pulse. Left out for noise pulses |
| `prepulse_db` | Prepulse level in dB SPL. This is the **absolute** level, not the amount above background. Only when there's a prepulse |
| `interval_ms` | Prepulse onset to pulse onset. Only for `prepulse+pulse` |

Sessions recorded with Boom Box 1.1 don't
have `pulse_stimulus` or `pulse_freq_hz` in `stimuli`. The same values are in `boom_box.trials`.

**Which moment the event time means:**

| `type` | Event time | Boom Box's own trial type |
|---|---|---|
| `pulse` | When the pulse left the computer | `startle` (tone-list protocols) or `pulse_alone` (PPI) |
| `prepulse+pulse` | When the **pulse** left the computer. The prepulse started `interval_ms` earlier | `prepulse_pulse` |
| `prepulse` | When the prepulse left the computer | `prepulse_alone` |
| `none` | The scheduled time; no sound played. Use these as a baseline for comparison | `no_stim` |

Example, from a short test session:

```json
"stimuli": [
  {"frame": 31, "video_time_s": 1.00001, "type": "pulse", "pulse_db": 30,
   "pulse_stimulus": "tone", "pulse_freq_hz": 8000},
  {"frame": 58, "video_time_s": 1.931327, "type": "prepulse+pulse",
   "pulse_db": 30, "pulse_stimulus": "tone", "pulse_freq_hz": 8000,
   "prepulse_db": 6.0, "interval_ms": 100.0},
  {"frame": 86, "video_time_s": 2.855554, "type": "none"},
  {"frame": 143, "video_time_s": 4.735476, "type": "prepulse", "prepulse_db": 6.0}
]
```

---

## 7. Timing limits

These matter when choosing the window to search for a startle.

- **The sound time is precise.** Tones are placed on the audio hardware's own
  clock, and the time recorded is when the sound left the computer. Sound takes
  a few more milliseconds to reach the animal.
- **The frame number can be slightly early.** `frame` is the last frame that had
  reached the computer when the sound played. A camera takes time to deliver each
  frame, so the frame actually being exposed at that moment is usually later.
  Unless `camera_latency_ms` was measured and set, this delay isn't corrected.
  It's currently `0` by default, and we haven't measured it for the lab's camera.
  **Don't treat `frame` as the exact first frame of the response. Search
  a window around it.**
- **Frames are coarse at 30 fps.** A frame lasts 33 ms, longer than the 10 ms
  tone. Check `fps_set`, since 60 and 90 fps can also be selected.

---

## 8. The `boom_box` object

| Field | What it is |
|---|---|
| `trials` | Per-trial detail (section 9) |
| `protocol` | The full protocol used, including its name, tone shape and background noise level |
| `protocol_name` | Its name, e.g. `Tone Volume Sensitivity` |
| `schedule` | The planned trials |
| `calibrated` | Whether a speaker calibration existed |
| `calibration` | The calibration values used |
| `audio_output` | Sound device, sample rate, system volume, and counts of audio problems (`clipped_blocks`, `underflows`). Both counts should be 0 |
| `microphone` | Mic used, or `null` if none |
| `files` | Names of the trials, log and audio files |
| `session_folder`, `time_reference` | Folder name, and a note on time units |

---

## 9. `boom_box.trials` and `_trials.csv`

One row for **every planned trial**, including any never reached in a session
that stopped early. Their actual-time columns are blank.

`stimuli[n]` is the same trial as `boom_box.trials[n]`, because any trials not
reached are always at the end.

**Trial columns**

| Column | Meaning |
|---|---|
| `trial` | Trial number, from 1 |
| `trial_type` | `startle`, `pulse_alone`, `prepulse_pulse`, `prepulse_alone` or `no_stim` |
| `scheduled_ms` | Planned time of the trial |
| `scheduled_frame` | Frame at the planned time; blank if recording had ended |
| `lead_ms` | Prepulse onset to pulse onset (`prepulse_pulse` only) |
| `experimenter`, `animal_id` | Repeated on each row |

**Stimulus columns.** Each of these exists twice, starting `pulse_` and
`prepulse_`. They're blank if the trial has no such stimulus.

| Column ending | Meaning |
|---|---|
| `_stimulus` | `tone` or `noise` |
| `_freq_hz` | Tone frequency. Blank for noise |
| `_level_db` | Level requested, in dB SPL |
| `_dbfs` | Digital output level used to produce it |
| `_calibration` | `calibrated`, `interpolated` (estimated from nearby calibrated frequencies) or `uncalibrated` |
| `_scheduled_ms` | Planned onset |
| `_actual_ms` | When the sound left the computer |
| `_late_ms` | How late it played. Normally 0 |
| `_frame` | Video frame at `_actual_ms` |
| `_mic_ms` | When the microphone heard it |
| `_mic_frame` | Video frame at `_mic_ms` |
| `_mic_minus_actual_ms` | Delay from the computer to the microphone |

**Frequency:** the built-in `Tone Volume Sensitivity` protocol plays 15 tones, three each at
4, 8, 12, 16 and 20 kHz, in a fixed order. Use `pulse_freq_hz` to group them.

**dB levels are requested, not measured.** They're only true dB SPL if
`_calibration` is `calibrated`. The microphone doesn't measure loudness.

**Microphone columns are a check on timing, and can be blank.** Only tones are
detected, not noise. A tone is left blank if it doesn't stand out clearly from
the background, which is more likely at 16–20 kHz, since many microphones are
less sensitive there. A blank doesn't mean the tone didn't play.

---

## 10. Audio

The MP4 has the microphone as an audio track (AAC), lined up with the video. The
`_audio.wav` file has the same recording at full quality. Neither is needed for
tracking. There are no visual markers in the video: nothing is drawn on the saved
frames to show when a tone played.

---

## 11. Recorded but not in the standard

Boom Box also records these. The standard leaves them out for now, so they stay
in `boom_box`.

| Possible field | Why it matters |
|---|---|
| Trial number (`trial`) | Links each stimulus directly to the detail row |
| Separate prepulse time and frame | `prepulse+pulse` entries give only the pulse's time |
| Calibration status per stimulus | Shows whether `pulse_db` is a true dB SPL |
| Microphone-measured time | An independent timing check |

---

## 12. Status

- The file format was checked with a short test session on a Mac, using the test
  camera. It hasn't yet been checked with the lab's camera in a real session.
- Windows support is written but hasn't yet been run on a PC.
- The standard is still a draft, so these details may change.
