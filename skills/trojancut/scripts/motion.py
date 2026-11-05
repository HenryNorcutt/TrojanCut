"""Motion-effect detection in references (numpy + ffmpeg): flashes, camera shake, zoom punches, speed ramps.

Frames are decoded once at 256 px wide (grey + mean colour). Per consecutive pair: global translation
by FFT phase correlation (sub-pixel peak, with the peak height as confidence), and, when translation
does not explain the change, the best zoom factor (grid search, phase correlation after scaling).

- flash: a run of <= 0.35 s whose luma is >= 35 above both neighbours, with matching colour before
  and after (so a bright shot between two cuts is not a flash).
- zoom: a run of frames whose scale changes >= 2.5 % per frame, total >= 8 %, lasting <= 0.5 s.
- shake: the high-pass part of the translation (minus a 0.36 s moving average) >= 1.2 px RMS for >= 0.2 s.
- ramp: within one shot, smoothed speed > 2x (or < 0.5x) the shot's median for >= 0.3 s.
Scene-detector "cuts" that are really a flash edge or a zoom punch are returned so the caller drops them.
"""
import subprocess

import numpy as np

AW = 256  # analysis width


def decode_small(path, max_seconds=120):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate,r_frame_rate", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    parts = (r.stdout.strip().splitlines() or ["0,0,0/0,0/0"])[0].split(",")
    w, h = int(parts[0] or 0), int(parts[1] or 0)
    fps = 0.0
    for v in parts[2:4]:
        try:
            n, d = v.split("/")
            if float(d) and float(n):
                fps = float(n) / float(d)
                break
        except ValueError:
            pass
    if not w or not h or fps <= 0:
        return None, 0.0
    fps = min(fps, 30.0)
    ah = max(16, int(round(AW * h / w / 2)) * 2)
    r = subprocess.run(["ffmpeg", "-v", "error", "-t", str(max_seconds), "-i", str(path), "-an", "-vf",
                        f"fps={fps:.6f},scale={AW}:{ah}:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True)
    n = len(r.stdout) // (AW * ah * 3)
    if n < 3:
        return None, fps
    return np.frombuffer(r.stdout[: n * AW * ah * 3], np.uint8).reshape(n, ah, AW, 3).astype(np.float32), fps


_WIN = {}


def _window(shape):
    if shape not in _WIN:
        _WIN[shape] = np.outer(np.hanning(shape[0]), np.hanning(shape[1])).astype(np.float32)
    return _WIN[shape]


def phase_corr(a, b):
    """Shift (dx, dy) that maps a onto b, and the normalised peak height (0..1)."""
    w = _window(a.shape)
    A = np.fft.rfft2((a - a.mean()) * w)
    B = np.fft.rfft2((b - b.mean()) * w)
    R = B * np.conj(A)
    R /= np.abs(R) + 1e-6
    r = np.fft.irfft2(R, s=a.shape)
    i = int(np.argmax(r))
    y, x = divmod(i, a.shape[1])
    peak = float(r.flat[i])

    def sub(v, n, axis):
        vm = r[(y, (x - 1) % n)] if axis else r[((y - 1) % n, x)]
        vp = r[(y, (x + 1) % n)] if axis else r[((y + 1) % n, x)]
        d = vm - 2 * peak + vp
        return v + (0.5 * (vm - vp) / d if d < 0 else 0.0)

    fx, fy = sub(x, a.shape[1], 1), sub(y, a.shape[0], 0)
    if fx > a.shape[1] / 2:
        fx -= a.shape[1]
    if fy > a.shape[0] / 2:
        fy -= a.shape[0]
    return fx, fy, peak


def zoom_img(img, s):
    """img scaled by s about its centre, same size (bilinear)."""
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    sy = (yy - h / 2) / s + h / 2
    sx = (xx - w / 2) / s + w / 2
    x0 = np.clip(np.floor(sx).astype(int), 0, w - 2)
    y0 = np.clip(np.floor(sy).astype(int), 0, h - 2)
    fx, fy = np.clip(sx - x0, 0, 1), np.clip(sy - y0, 0, 1)
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy) +
            img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def best_zoom(a, b):
    """Scale s (b ~ a zoomed by s) and its match quality, judged on the central 70 %."""
    h, w = a.shape
    ch, cw = int(h * 0.15), int(w * 0.15)
    best = (1.0, -1.0)
    bb = b[ch:h - ch, cw:w - cw]
    bc = bb - bb.mean()
    bn = np.sqrt((bc * bc).sum())

    def corr(s):
        z = zoom_img(a, s)[ch:h - ch, cw:w - cw]
        zc = z - z.mean()
        return float((zc * bc).sum() / (np.sqrt((zc * zc).sum()) * bn + 1e-6))

    for s in (0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12, 1.16):  # coarse, then refine around the best
        c = corr(s)
        if c > best[1]:
            best = (s, c)
    for s in np.arange(best[0] - 0.03, best[0] + 0.031, 0.01):
        c = corr(float(s))
        if c > best[1]:
            best = (float(s), c)
    return best


def _runs(mask):
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i))
            start = None
    return out


def _smooth(x, n):
    n = max(1, int(n)) | 1
    pad = np.pad(x, (n // 2, n // 2), mode="edge")
    return np.convolve(pad, np.ones(n) / n, mode="valid")


def _summary(events, dur, beats):
    beats = np.asarray(beats, float)
    on = [e for e in events if len(beats) and np.min(np.abs(beats - e["t"])) <= 0.07]
    return {"events": events, "rate_per_10s": round(10 * len(events) / max(dur, 1e-6), 2),
            "typical_duration": round(float(np.median([e["duration"] for e in events])), 3) if events else 0.0,
            "strength": round(float(np.median([e["strength"] for e in events])), 3) if events else 0.0,
            "on_beat_share": round(len(on) / len(events), 2) if events else 0.0}


def analyze(path, cuts, beats):
    """Return (motion dict, list of scene cuts that are really flash edges or zoom punches)."""
    frames, fps = decode_small(path)
    empty = {k: _summary([], 1, beats) for k in ("flash", "shake", "zoom", "ramp")}
    if frames is None:
        return empty, []
    n = len(frames)
    dur = n / fps
    t = np.arange(n) / fps
    grey = frames @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    luma = grey.mean(axis=(1, 2))
    meanc = frames.mean(axis=(1, 2))

    # ---- flashes
    flash_mask = np.zeros(n, bool)
    flash_events = []
    maxlen = max(1, int(round(0.35 * fps)))
    cand = np.zeros(n, bool)
    for i in range(n):
        lo, hi = max(0, i - maxlen - 2), min(n, i + maxlen + 3)
        ref = np.concatenate([luma[lo:max(lo, i - maxlen)], luma[min(hi, i + maxlen + 1):hi]])
        if len(ref) and luma[i] - np.median(ref) >= 35:
            cand[i] = True
    for a, b in _runs(cand):
        if b - a > maxlen or a == 0 or b >= n:
            continue
        before, after = meanc[a - 1], meanc[b]
        if np.abs(before - after).sum() > 45 or luma[a:b].max() - max(luma[a - 1], luma[b]) < 35:
            continue
        flash_mask[a:b] = True
        flash_events.append({"t": round(float(t[a]), 3), "duration": round((b - a) / fps, 3),
                             "strength": round(float((luma[a:b].max() - (luma[a - 1] + luma[b]) / 2) / 255), 3)})

    # ---- pairwise translation (skip pairs across scene cuts or touching flashes)
    cut_idx = set(int(round(c * fps)) for c in cuts)
    dx = np.zeros(n - 1)
    dy = np.zeros(n - 1)
    peak = np.zeros(n - 1)
    valid = np.ones(n - 1, bool)
    for i in range(n - 1):
        if flash_mask[i] or flash_mask[i + 1]:
            valid[i] = False
            continue
        dx[i], dy[i], peak[i] = phase_corr(grey[i], grey[i + 1])
    # a static or smoothly moving camera correlates strongly; weak = translation does not explain the change
    weak = valid & (peak < 0.08)

    # ---- zoom punches: where translation fits poorly, measure scale (half resolution for speed)
    small = grey[:, ::2, ::2]
    logs = np.zeros(n - 1)
    check = weak | np.isin(np.arange(n - 1) + 1, list(cut_idx))
    for i in np.where(check)[0]:
        if flash_mask[i] or flash_mask[i + 1] or np.abs(meanc[i] - meanc[i + 1]).sum() > 40:
            continue
        sc, q = best_zoom(small[i], small[i + 1])
        if q >= 0.8:
            logs[i] = np.log(sc)
    zoom_events, zoom_mask = [], np.zeros(n - 1, bool)
    fast = np.abs(logs) >= 0.025
    for sign in (1, -1):
        for a, b in _runs(fast & (np.sign(logs) == sign)):
            total = float(np.sum(logs[a:b]))
            if abs(total) < 0.08 or (b - a) / fps > 0.3 or abs(total) / (b - a) < 0.04:
                continue  # slow drift or the settle of a punch, not a punch
            z = b  # absorb the settle that follows (opposite sign)
            while z < n - 1 and z - a < int(0.8 * fps) and np.sign(logs[z]) == -sign and abs(logs[z]) >= 0.006:
                z += 1
            zoom_mask[a:z] = True
            zoom_events.append({"t": round(float(t[a]), 3), "duration": round((z - a) / fps, 3),
                                "strength": round(float(np.exp(abs(total)) - 1), 3)})
    zoom_events.sort(key=lambda e: e["t"])
    invalid = ~valid | zoom_mask
    for c in cut_idx:
        if 0 < c <= n - 1:
            invalid[c - 1] = True

    # ---- shake: high-pass of the camera *position* (integrated translation), per shot
    def fill(v):
        idx = np.arange(len(v))
        ok = ~np.isnan(v)
        return np.interp(idx, idx[ok], v[ok]) if ok.sum() >= 2 else np.zeros_like(v)

    fx = fill(np.where(invalid, np.nan, dx))
    fy = fill(np.where(invalid, np.nan, dy))
    px, py = np.cumsum(fx), np.cumsum(fy)
    k = int(round(0.4 * fps))
    dev = np.hypot(px - _smooth(px, k), py - _smooth(py, k))
    energy = np.sqrt(_smooth(dev ** 2, int(round(0.2 * fps))))
    # reversals: shake goes back and forth, a pan does not
    rev = np.zeros(n - 1)
    for i in range(1, n - 1):
        rev[i] = (fx[i] * fx[i - 1] < 0 and max(abs(fx[i]), abs(fx[i - 1])) > 1) or \
                 (fy[i] * fy[i - 1] < 0 and max(abs(fy[i]), abs(fy[i - 1])) > 1)
    rev = _smooth(rev, int(round(0.24 * fps)))
    shake_mask = (energy >= 2.5 * AW / 256) & (rev >= 0.3) & ~invalid
    shake_events = []
    for a, b in _runs(_smooth(shake_mask.astype(float), 3) > 0.5):
        if (b - a) / fps < 0.2:
            continue
        shake_events.append({"t": round(float(t[a]), 3), "duration": round((b - a) / fps, 3),
                             "strength": round(float(energy[a:b].max() / AW), 4)})

    # ---- speed ramps per shot
    bounds = [0] + sorted(c for c in cut_idx if 0 < c < n) + [n - 1]
    ramp_events = []
    sp = _smooth(np.hypot(fx, fy), 3)
    for a, b in zip(bounds, bounds[1:]):
        if (b - a) / fps < 1.0:
            continue
        seg = sp[a:b]
        okseg = ~(invalid[a:b] | shake_mask[a:b])
        if okseg.sum() < 0.6 * len(seg):
            continue
        base = float(np.median(seg[okseg]))
        if base < 0.8:
            continue
        for mask, kind in ((seg > 2.0 * base + 0.5, "fast"), (seg < 0.5 * base, "slow")):
            for r0, r1 in _runs(mask & okseg):
                if (r1 - r0) / fps >= 0.3 and r1 - r0 < 0.8 * len(seg):
                    ratio = float(np.median(seg[r0:r1]) / base)
                    if kind == "slow" and ratio < 0.1:
                        continue  # a freeze or a decode stutter, not slow motion
                    ramp_events.append({"t": round(float(t[a + r0]), 3), "duration": round((r1 - r0) / fps, 3),
                                        "strength": round(ratio, 2), "kind": kind})

    false_cuts = []
    for c in cuts:
        i = int(round(c * fps))
        if any(flash_mask[max(0, i - 2):min(n, i + 3)]) or any(zoom_mask[max(0, i - 3):min(n - 1, i + 2)]):
            false_cuts.append(c)
    motion = {"flash": _summary(flash_events, dur, beats), "shake": _summary(shake_events, dur, beats),
              "zoom": _summary(zoom_events, dur, beats), "ramp": _summary(sorted(ramp_events, key=lambda e: e["t"]),
                                                                          dur, beats)}
    return motion, false_cuts
