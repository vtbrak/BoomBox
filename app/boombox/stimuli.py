"""Stimulus waveforms: raised-cosine tone bursts and noise bursts.

Levels are expressed in dB re full scale (dBFS):
  * tones: peak amplitude, so a full-scale sine is 0 dBFS
  * noise: RMS amplitude, so noise with RMS 1.0 is 0 dBFS
"""

import numpy as np


def db_to_amp(dbfs):
    return float(10.0 ** (dbfs / 20.0))


def envelope(rise_ms, plateau_ms, fall_ms, fs):
    """Raised-cosine (cos^2) onset/offset envelope. Starts and ends at 0."""
    nr = int(round(rise_ms * fs / 1000.0))
    npl = int(round(plateau_ms * fs / 1000.0))
    nf = int(round(fall_ms * fs / 1000.0))
    rise = 0.5 * (1.0 - np.cos(np.pi * np.arange(nr) / max(nr, 1)))
    plateau = np.ones(npl)
    fall = 0.5 * (1.0 + np.cos(np.pi * np.arange(1, nf + 1) / max(nf, 1)))
    return np.concatenate([rise, plateau, fall])


def tone_burst(freq_hz, dbfs, rise_ms, plateau_ms, fall_ms, fs):
    env = envelope(rise_ms, plateau_ms, fall_ms, fs)
    t = np.arange(env.size) / fs
    return (db_to_amp(dbfs) * env * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def noise_burst(dbfs, rise_ms, plateau_ms, fall_ms, fs, rng=None):
    rng = rng or np.random.default_rng()
    env = envelope(rise_ms, plateau_ms, fall_ms, fs)
    noise = rng.standard_normal(env.size)
    noise /= np.sqrt(np.mean(noise ** 2))
    return (db_to_amp(dbfs) * env * noise).astype(np.float32)


def make_stimulus(stim, dbfs, fs):
    """stim: dict with 'stimulus' ('tone'|'noise'), 'freq_hz', 'rise_ms', 'plateau_ms', 'fall_ms'."""
    if stim.get("stimulus", "tone") == "noise":
        return noise_burst(dbfs, stim["rise_ms"], stim["plateau_ms"], stim["fall_ms"], fs)
    return tone_burst(stim["freq_hz"], dbfs, stim["rise_ms"], stim["plateau_ms"], stim["fall_ms"], fs)
