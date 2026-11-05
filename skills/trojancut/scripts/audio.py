"""Audio decoding and analysis in numpy: onset envelope, tempo, beat grid, downbeats, energy.

Beat tracking: spectral-flux onset envelope -> autocorrelation tempo (60-200 BPM with a soft
preference around 120) -> phase by comb alignment -> period and phase refined by least squares on
the onset peaks nearest each predicted beat. Constant-tempo music is assumed (no drift model).
"""
import math
import subprocess
from pathlib import Path

import numpy as np

from common import fail

SR = 22050
HOP = 256
NFFT = 1024
FPS = SR / HOP


def decode(path, sr=SR, start=None, dur=None, channels=1):
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.4f}"]
    if dur is not None:
        cmd += ["-t", f"{max(0.0, dur):.4f}"]
    cmd += ["-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        msg = r.stderr.decode(errors="replace").strip().splitlines()
        fail(f"cannot decode audio from {Path(path).name}: {msg[-1] if msg else 'ffmpeg error'}")
    x = np.frombuffer(r.stdout, "<f4").astype(np.float64)
    return x.reshape(-1, channels) if channels > 1 else x


def rms_db(x):
    if len(x) == 0:
        return -120.0
    return 20 * math.log10(math.sqrt(float(np.mean(np.square(x)))) + 1e-9)


def stft_mag(x):
    if len(x) < NFFT:
        x = np.pad(x, (0, NFFT - len(x)))
    n = 1 + (len(x) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(NFFT)[None, :]
    return np.abs(np.fft.rfft(frames, axis=1))


def onset_envelope(x):
    mag = stft_mag(x)
    logm = np.log1p(100.0 * mag)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    w = int(FPS * 0.5) | 1
    local = np.convolve(flux, np.ones(w) / w, mode="same")
    env = np.maximum(0.0, flux - local)
    return env


def _parabolic(y, i):
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        d = a - 2 * b + c
        if d < 0:
            return i + 0.5 * (a - c) / d
    return float(i)


def _sample(env, t):
    """Max of env within +-1 frame around fractional frame positions t."""
    i = np.clip(np.round(t).astype(int), 1, len(env) - 2)  # clip, never drop: output aligns with t
    return np.maximum(np.maximum(env[i - 1], env[i]), env[i + 1]) if len(i) else np.zeros(0)


def beat_track(x):
    """Return dict(bpm, beats[s], downbeat_index, confidence) for a mono signal at SR."""
    dur = len(x) / SR
    env = onset_envelope(x)
    if len(env) < FPS * 2 or env.max() <= 1e-6:
        return {"bpm": 0.0, "beats": [], "downbeat": 0, "confidence": 0.0, "duration": dur}
    e = env / (env.max() + 1e-12)
    e0 = e - e.mean()
    n = len(e0)
    nfft = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(e0, nfft)
    ac = np.fft.irfft(spec * np.conj(spec), nfft)[:n]
    ac = ac / (np.arange(n, 0, -1))
    if ac[0] <= 0:
        return {"bpm": 0.0, "beats": [], "downbeat": 0, "confidence": 0.0, "duration": dur}
    ac = ac / ac[0]
    lo, hi = int(FPS * 60 / 200), int(FPS * 60 / 60) + 1
    lags = np.arange(lo, min(hi, n - 1))
    if len(lags) < 3:
        return {"bpm": 0.0, "beats": [], "downbeat": 0, "confidence": 0.0, "duration": dur}
    bpms = 60 * FPS / lags
    prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    score = np.maximum(ac[lags], 0) * prior
    k = int(np.argmax(score))
    lag = _parabolic(ac, lags[k])
    conf = float(ac[lags[k]] - np.median(ac[lags]))

    # phase by comb alignment
    nb = max(1, int((n - 1) / lag))
    best, phase = -1.0, 0.0
    for p in np.arange(0, lag, 0.5):
        s = _sample(e, p + lag * np.arange(nb)).sum()
        if s > best:
            best, phase = s, p
    # least-squares refinement on the strongest local onset near each beat
    period = lag
    for _ in range(2):
        ks, ts = [], []
        for j in range(nb + 1):
            c = phase + j * period
            a, b = int(c - period * 0.2), int(c + period * 0.2) + 1
            if a < 0 or b >= n:
                continue
            seg = e[a:b]
            if seg.max() < 0.1:
                continue
            m = a + int(np.argmax(seg))
            ks.append(j)
            ts.append(_parabolic(e, m))
        if len(ks) >= 4:
            A = np.vstack([np.ones(len(ks)), ks]).T
            phase, period = np.linalg.lstsq(A, np.array(ts), rcond=None)[0]
    t0 = (phase * HOP + NFFT / 2 - HOP) / SR
    p_s = period * HOP / SR
    t0, p_s = refine_on_waveform(x, t0, p_s, dur)
    t0 = t0 - p_s * math.floor(t0 / p_s)
    beats = np.arange(t0, dur - 1e-6, p_s)
    strength = _sample(e, (beats * SR - NFFT / 2 + HOP) / HOP)
    down = 0
    if len(strength) >= 8:
        sums = [strength[i::4].mean() for i in range(4)]
        down = int(np.argmax(sums))
    return {"bpm": round(60.0 / p_s, 2), "beats": [round(float(b), 4) for b in beats], "downbeat": down,
            "confidence": round(conf, 3), "duration": round(dur, 3), "period": p_s}


def refine_on_waveform(x, t0, p, dur, fine=64):
    """Sharpen phase and period: for each predicted beat, the steepest rise of the short-time level
    (fine hop, ~3 ms) within +-20 % of a beat, then a least-squares line through those onsets."""
    n = len(x) // fine
    if n < 8:
        return t0, p
    lev = np.sqrt(np.mean(np.square(x[: n * fine].reshape(n, fine)), axis=1)) + 1e-6
    rise = np.diff(np.log(lev), prepend=np.log(lev[0]))
    rise = np.where(lev > 0.1 * np.percentile(lev, 95), rise, 0.0)
    ks, ts = [], []
    first = -math.floor(t0 / p)
    for j in range(first, int((dur - t0) / p) + 1):
        c = t0 + j * p
        a, b = int((c - 0.2 * p) * SR / fine), int((c + 0.2 * p) * SR / fine) + 1
        if a < 1 or b >= n:
            continue
        i = a + int(np.argmax(rise[a:b]))
        if rise[i] < 0.3:
            continue
        ks.append(j)
        ts.append((i + 0.5) * fine / SR)
    if len(ks) < 6:
        return t0, p
    A = np.vstack([np.ones(len(ks)), ks]).T
    (c0, c1), *_ = np.linalg.lstsq(A, np.array(ts), rcond=None)
    if abs(c1 - p) > 0.02 * p:
        return t0, p
    return float(c0), float(c1)


def grid_from_period(period, dur, phase=0.0):
    beats = np.arange(phase, dur - 1e-6, period)
    return {"bpm": round(60.0 / period, 2), "beats": [round(float(b), 4) for b in beats], "downbeat": 0,
            "confidence": 0.0, "duration": round(dur, 3), "period": period}


def bpm_from_shot(shot):
    """A plausible tempo whose beat (or a multiple) equals the shot length."""
    if shot <= 0:
        return 120.0
    bpm = 60.0 / shot
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return bpm


def beat_energy(x, beats, period):
    """Per-beat loudness (dB) and onset density, used to find the strongest window."""
    env = onset_envelope(x)
    out_l, out_o = [], []
    for b in beats:
        a, z = int(b * SR), int((b + period) * SR)
        out_l.append(rms_db(x[a:z]))
        fa, fz = int(b * FPS), int((b + period) * FPS) + 1
        seg = env[fa:fz]
        out_o.append(float(seg.sum()) if len(seg) else 0.0)
    return np.array(out_l), np.array(out_o)


def classify_shape(x, sr=SR):
    """'hit' (sharp attack, decays), 'riser' (level rises to the end), 'whoosh' (noise that swells and
    falls) or 'other'."""
    if len(x) < sr * 0.03:
        return "other"
    fl = int(sr * 0.02)
    nfr = len(x) // fl
    envl = np.sqrt(np.mean(np.square(x[: nfr * fl].reshape(nfr, fl)), axis=1)) + 1e-9
    peak = int(np.argmax(envl))
    pos = peak / max(1, nfr - 1)
    q = max(1, nfr // 4)
    first, last = envl[:q].mean(), envl[-q:].mean()
    # attack: frames from 10% to 90% of peak before the peak
    pre = envl[: peak + 1]
    start = int(np.argmax(pre >= 0.1 * envl[peak]))
    attack = (peak - start) * 0.02
    # tonality: share of energy in the 5 strongest bins, averaged over loud frames
    mag = stft_mag(x) ** 2
    loud = mag.sum(axis=1) > 0.05 * mag.sum(axis=1).max()
    tonal = float(np.mean(np.sort(mag[loud], axis=1)[:, -5:].sum(axis=1) / (mag[loud].sum(axis=1) + 1e-12)))
    if pos <= 0.15 and attack <= 0.04 and last < 0.3 * envl[peak]:
        return "hit"
    if pos >= 0.7 and last > 2.5 * first:
        return "riser"
    if tonal < 0.4 and 0.15 < pos < 0.85 and first < 0.6 * envl[peak] and last < 0.6 * envl[peak]:
        return "whoosh"
    return "other"
