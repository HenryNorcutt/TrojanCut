#!/usr/bin/env python3
"""Synthesize TrojanCut's built-in sound-effect pack deterministically (numpy only, no downloads).

  python3 make_sfx.py --out DIR      (default: ../sfx next to this script)

Writes 44.1 kHz mono 16-bit WAVs peak-normalised to -1 dBFS plus manifest.json. A fixed-seed
xorshift generator makes every run byte-identical on every machine.
"""
import argparse
import json
import math
import struct
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
PEAK_DB = -1.0


class Rng:
    """xorshift64* - fixed across numpy versions and platforms."""

    def __init__(self, seed):
        self.s = (seed * 0x9E3779B97F4A7C15 + 1) & 0xFFFFFFFFFFFFFFFF

    def uniform(self, n):
        out = np.empty(n, np.float64)
        s = self.s
        for i in range(n):
            s ^= (s >> 12)
            s ^= (s << 25) & 0xFFFFFFFFFFFFFFFF
            s ^= (s >> 27)
            out[i] = ((s * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF) / 2.0 ** 64
        self.s = s
        return out

    def noise(self, n):
        return self.uniform(n) * 2.0 - 1.0


def t_axis(dur):
    return np.arange(int(round(dur * SR))) / SR


def lowpass(x, cutoff):
    """One-pole low-pass; cutoff may be an array (Hz per sample)."""
    c = np.broadcast_to(np.asarray(cutoff, np.float64), x.shape)
    a = 1.0 - np.exp(-2.0 * math.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def bandpass(x, centre, q=2.0):
    """State-variable band-pass; centre may vary per sample."""
    f = np.broadcast_to(np.asarray(centre, np.float64), x.shape)
    g = 2.0 * np.sin(math.pi * np.minimum(f, SR / 6) / SR)
    damp = 1.0 / q
    low = band = 0.0
    y = np.empty_like(x)
    for i in range(len(x)):
        high = x[i] - low - damp * band
        band += g[i] * high
        low += g[i] * band
        y[i] = band
    return y


def fade(x, a=0.003, r=0.01):
    n_a, n_r = max(1, int(a * SR)), max(1, int(r * SR))
    env = np.ones(len(x))
    env[:n_a] = np.linspace(0, 1, n_a)
    env[-n_r:] = np.minimum(env[-n_r:], np.linspace(1, 0, n_r))
    return x * env


def sweep_sine(f0, f1, dur, curve=1.0):
    t = t_axis(dur)
    f = f0 + (f1 - f0) * (t / dur) ** curve
    return np.sin(2 * math.pi * np.cumsum(f) / SR), t


# ---------------------------------------------------------------- sound designs

def whoosh(rng, v):
    dur = [0.7, 0.55, 0.9][v]
    t = t_axis(dur)
    n = rng.noise(len(t))
    peak = [0.5, 0.45, 0.6][v]
    env = np.exp(-((t / dur - peak) / 0.22) ** 2)
    centre = 300 + 3200 * np.exp(-((t / dur - peak) / 0.3) ** 2)
    return fade(bandpass(n, centre, q=1.5) * env)


def swoosh(rng, v):
    dur = [0.35, 0.3, 0.42][v]
    t = t_axis(dur)
    n = rng.noise(len(t))
    env = (t / dur) ** 1.5 * np.exp(-((t / dur) ** 6) * 4)
    centre = [1200, 1800, 900][v] + 5000 * (t / dur)
    return fade(bandpass(n, centre, q=2.5) * env)


def riser(rng, v):
    dur = [1.6, 2.0, 1.2][v]
    s, t = sweep_sine([200, 150, 300][v], [1800, 2400, 2000][v], dur, curve=2.0)
    n = bandpass(rng.noise(len(t)), 800 + 5000 * (t / dur) ** 2, q=1.2)
    env = (t / dur) ** 2.2
    x = (0.6 * s + 0.6 * n) * env
    return fade(x, a=0.01, r=0.004)


def impact(rng, v):
    dur = [0.9, 1.2, 0.7][v]
    t = t_axis(dur)
    f = [55, 48, 65][v] * (1 + 1.5 * np.exp(-t * 30))
    body = np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * [5, 4, 7][v])
    crack = lowpass(rng.noise(len(t)), 3500) * np.exp(-t * 45)
    return fade(body + 0.8 * crack, a=0.0015, r=0.05)


def subdrop(rng, v):
    dur = [1.4, 1.8, 1.1][v]
    s, t = sweep_sine([120, 100, 140][v], [30, 28, 35][v], dur, curve=0.5)
    return fade(s * np.exp(-t * [2.0, 1.6, 2.6][v]), a=0.004, r=0.08)


def hit(rng, v):
    dur = [0.3, 0.4, 0.25][v]
    t = t_axis(dur)
    tone = np.sin(2 * math.pi * [180, 140, 240][v] * t) * np.exp(-t * 18)
    snap = bandpass(rng.noise(len(t)), [2500, 1800, 3500][v], q=1.0) * np.exp(-t * 60)
    return fade(tone + 1.2 * snap, a=0.001, r=0.02)


def glitch(rng, v):
    dur = [0.4, 0.5, 0.3][v]
    t = t_axis(dur)
    seg = int(SR * [0.025, 0.018, 0.035][v])
    x = np.zeros(len(t))
    u = rng.uniform(len(t) // seg + 2)
    for k in range(0, len(t), seg):
        r = u[k // seg]
        part = t[k:k + seg]
        if r < 0.3:
            x[k:k + seg] = np.sign(np.sin(2 * math.pi * (400 + 3000 * r) * part)) * 0.6
        elif r < 0.6:
            x[k:k + seg] = rng.noise(len(part)) * 0.8
        elif r < 0.8:
            x[k:k + seg] = np.sin(2 * math.pi * (100 + 1500 * r) * part)
    return fade(x, a=0.001, r=0.01)


def pop(rng, v):
    dur = [0.12, 0.15, 0.1][v]
    s, t = sweep_sine([900, 700, 1200][v], [250, 200, 350][v], dur, curve=0.4)
    return fade(s * np.exp(-t * 35), a=0.0008, r=0.01)


def shutter(rng, v):
    dur = [0.25, 0.3, 0.2][v]
    t = t_axis(dur)
    x = np.zeros(len(t))
    for c0, gain in ((0.0, 1.0), ([0.09, 0.12, 0.07][v], 0.7)):
        tt = t - c0
        m = tt >= 0
        x[m] += gain * bandpass(rng.noise(int(m.sum())), [3000, 2400, 3800][v], q=3.0) * np.exp(-tt[m] * 90)
    return fade(x, a=0.0005, r=0.01)


DESIGNS = [("whoosh", whoosh, ["air", "transition"]), ("swoosh", swoosh, ["fast", "transition"]),
           ("riser", riser, ["build", "tension"]), ("impact", impact, ["boom", "heavy"]),
           ("subdrop", subdrop, ["bass", "drop"]), ("hit", hit, ["punch", "accent"]),
           ("glitch", glitch, ["digital", "stutter"]), ("pop", pop, ["light", "ui"]),
           ("shutter", shutter, ["camera", "click"])]
VARIANTS = 3


def to_pcm(x):
    x = x / (np.max(np.abs(x)) + 1e-12) * 10 ** (PEAK_DB / 20)
    return np.round(x * 32767).astype("<i2")


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def generate(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.wav"):
        old.unlink()
    manifest = []
    for k, (name, fn, tags) in enumerate(DESIGNS):
        for v in range(VARIANTS):
            rng = Rng(1000 * (k + 1) + v)
            pcm = to_pcm(fn(rng, v))
            fname = f"{name}_{v + 1}.wav"
            write_wav(out / fname, pcm)
            x = pcm.astype(np.float64) / 32768
            manifest.append({"name": fname, "type": name, "duration": round(len(x) / SR, 4),
                             "peak": round(20 * math.log10(np.max(np.abs(x))), 2),
                             "loudness": round(20 * math.log10(math.sqrt(float(np.mean(x ** 2))) + 1e-9), 2),
                             "tags": tags})
    (out / "manifest.json").write_text(json.dumps({"version": 1, "sample_rate": SR, "sounds": manifest},
                                                  indent=1) + "\n")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "sfx"))
    a = ap.parse_args()
    m = generate(a.out)
    print(f"wrote {len(m)} sounds to {a.out}")


if __name__ == "__main__":
    sys.exit(main())
