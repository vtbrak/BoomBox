"""Clap test: claps are found in the audio and turned into a camera latency."""

import unittest

import numpy as np

from boombox import claptest


def clap_audio(fs, clap_times, seconds=6.0, noise=0.002):
    rng = np.random.default_rng(1)
    x = rng.normal(0, noise, int(seconds * fs))
    burst = rng.normal(0, 0.5, int(0.03 * fs)) * np.exp(-np.arange(int(0.03 * fs)) / (0.006 * fs))
    for t in clap_times:
        i = int(t * fs)
        x[i:i + len(burst)] += burst
    return x.astype(np.float32)


class FindClapsTests(unittest.TestCase):
    def test_each_clap_is_found_within_a_millisecond(self):
        fs, times = 48000, [1.0, 2.3, 3.1, 4.75]
        found = [i / fs for i in claptest.find_claps(clap_audio(fs, times), fs)]
        self.assertEqual(len(found), len(times))
        for got, want in zip(found, times):
            self.assertAlmostEqual(got, want, delta=0.001)

    def test_quiet_room_has_no_claps(self):
        self.assertEqual(claptest.find_claps(clap_audio(48000, []), 48000), [])
        self.assertEqual(claptest.find_claps(np.zeros(0), 48000), [])

    def test_one_clap_is_not_counted_twice(self):
        fs = 48000
        self.assertEqual(len(claptest.find_claps(clap_audio(fs, [1.0, 1.1]), fs)), 1)


class LatencyTests(unittest.TestCase):
    def test_latency_is_recovered_from_simulated_claps(self):
        # Frames exposed every 1/30 s arrive 45 ms later; claps fall anywhere between frames.
        fps, true_ms = 30, 45.0
        rng = np.random.default_rng(2)
        exposures = np.arange(0, 60, 1 / fps)
        values = []
        for clap in rng.uniform(1, 59, 400):
            first = exposures[np.searchsorted(exposures, clap)]      # first frame after the clap
            values.append(claptest.latency_ms(first + true_ms / 1000, clap, fps))
        mean, sd, n = claptest.summarize(values)
        self.assertEqual(n, 400)
        self.assertAlmostEqual(mean, true_ms, delta=2.0)
        self.assertLess(sd, 1000 / fps)

    def test_summarize_handles_none_and_one(self):
        self.assertEqual(claptest.summarize([]), (None, None, 0))
        self.assertEqual(claptest.summarize([40.0]), (40.0, 0.0, 1))


class FrameCollectorTests(unittest.TestCase):
    def test_frames_are_shrunk_to_fit_memory_and_times_are_raw(self):
        fc = claptest.FrameCollector(1920, 1080, 90, seconds=15, latency_s=0.05)
        self.assertGreater(fc.step, 1)
        frame = np.zeros((1080, 1920), np.uint8)
        for t in (1.0, 1.1, 1.2):
            fc.push(frame, t - 0.05)            # the camera had already subtracted its latency
        self.assertEqual(fc.frames[0].shape, (len(range(0, 1080, fc.step)), len(range(0, 1920, fc.step))))
        self.assertAlmostEqual(fc.times[1], 1.1)
        self.assertEqual([fc.index_at(t) for t in (0.5, 1.05, 1.1, 9.0)], [0, 0, 1, 2])


if __name__ == "__main__":
    unittest.main()
