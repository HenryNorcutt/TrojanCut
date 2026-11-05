"""Music layout: which song plays when, from which part, and how songs join.

Songs keep their own tempo (no time-stretching). Each segment maps output time to song time 1:1,
so the output beat grid is the playing song's grid shifted by (segment.start - segment.src_in).
"""
import numpy as np

import audio
from common import fail

FADE_RULE_TEMPO_TOL = 0.06   # "Claude decides": crossfade only between songs within 6 % tempo (or 2x)


def analyze_song(path):
    x = audio.decode(path)
    if len(x) < audio.SR:
        fail(f"{path.name} is too short to use as music (under 1 s)")
    g = audio.beat_track(x)
    dur = len(x) / audio.SR
    if g["bpm"] <= 0:
        g = audio.grid_from_period(0.5, dur)
    period = g["period"]
    beats = np.array(g["beats"])
    loud, ons = audio.beat_energy(x, beats, period)
    return {"duration": dur, "bpm": g["bpm"], "period": period, "beats": beats, "downbeat": g["downbeat"],
            "loud": loud, "onset": ons}


def nearest_beat(info, t):
    b = info["beats"]
    i = int(np.argmin(np.abs(b - t)))
    return i, float(b[i])


def bars(info):
    return info["beats"][info["downbeat"]::4]


def auto_window(info, length):
    """Start index (a bar line) of the highest-energy window of `length` seconds."""
    nb = max(1, int(round(length / info["period"])))
    beats = info["beats"]
    if nb >= len(beats):
        return 0, len(beats)
    z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
    score = z(info["loud"]) + z(info["onset"])
    csum = np.concatenate([[0.0], np.cumsum(score)])
    best, best_i = -1e18, 0
    starts = list(range(info["downbeat"], len(beats) - nb + 1, 4)) or [0]
    for i in starts:
        s = (csum[i + nb] - csum[i]) / nb
        if s > best + 1e-9:
            best, best_i = s, i
    return best_i, nb


def switch_kind(a, b, wanted):
    if wanted == "cut":
        return "cut", "brief asks for hard cuts between songs"
    if wanted == "fade":
        return "fade", "brief asks for quick fades between songs"
    ratio = a["bpm"] / max(b["bpm"], 1e-6)
    close = min(abs(ratio - 1), abs(ratio - 2), abs(ratio - 0.5))
    if close <= FADE_RULE_TEMPO_TOL:
        return "fade", f"tempos match ({a['bpm']:.0f} vs {b['bpm']:.0f} BPM), so a one-beat crossfade blends cleanly"
    return "cut", (f"tempos differ ({a['bpm']:.0f} vs {b['bpm']:.0f} BPM); a crossfade would clash, "
                   "so cut hard on the beat")


def layout(songs, target, min_s, max_s, switch_pref):
    """songs: list of dict(file, info, part). Returns (segments, switches, fit, duration).

    target: preferred length when parts are auto; chosen parts keep their own length when it fits.
    """
    n = len(songs)
    # nominal length of each song (output seconds) before fitting
    chosen = []
    for s in songs:
        info, part = s["info"], s["part"]
        if isinstance(part, (list, tuple)):
            a, b = float(part[0]), float(part[1])
            if not (0 <= a < b):
                fail(f"music part for {s['file']} must be start < end, got {part}")
            if a >= info["duration"] - 0.5:
                fail(f"music part for {s['file']} starts at {a:.1f}s but the song is {info['duration']:.1f}s long")
            ia, ta = nearest_beat(info, a)
            nb = max(1, int(round((min(b, info["duration"]) - ta) / info["period"])))
            s["src_in"], s["beats_n"] = ta, nb
            chosen.append(True)
        else:
            chosen.append(False)
    chosen_total = sum(s["beats_n"] * s["info"]["period"] for s, c in zip(songs, chosen) if c)
    n_auto = n - sum(chosen)
    fit = "as chosen"
    if n_auto:
        rest = max(target - chosen_total, 0.0)
        for s, c in zip(songs, chosen):
            if not c:
                info = s["info"]
                want = max(rest / n_auto, 4 * info["period"]) if rest > 0 else 4 * info["period"]
                i0, nb = auto_window(info, want)
                s["src_in"], s["beats_n"] = float(info["beats"][i0]), nb
        if all(not c for c in chosen):
            fit = "auto parts"
    seq = list(songs)
    total = sum(s["beats_n"] * s["info"]["period"] for s in seq)
    if total > max_s + 1e-6:
        scale = target / total
        for s in seq:
            s["beats_n"] = max(2, int(round(s["beats_n"] * scale)))
        fit = f"trimmed chosen parts from {total:.1f}s to fit {min_s:g}-{max_s:g}s"
    elif total < min_s - 1e-6:
        base = list(seq)
        while sum(s["beats_n"] * s["info"]["period"] for s in seq) < target:
            seq.append(dict(base[len(seq) % len(base)]))
        fit = f"looped chosen parts ({total:.1f}s) to fit {min_s:g}-{max_s:g}s"

    # lay out in time, with switches
    segs, switches = [], []
    t = 0.0
    for k, s in enumerate(seq):
        info = s["info"]
        length = s["beats_n"] * info["period"]
        seg = {"file": s["file"], "src_in": round(s["src_in"], 4), "start": round(t, 4), "bpm": info["bpm"],
               "period": info["period"], "part": s["part"] if isinstance(s["part"], str) else list(s["part"])}
        nominal_end = t + length
        if k + 1 < len(seq):
            kind, why = switch_kind(info, seq[k + 1]["info"], switch_pref)
            if kind == "fade":
                sec = info["period"]
                # bar line of this song nearest to where the fade should start
                bl = bars(info) - seg["src_in"] + t
                bl = bl[(bl > t + 2 * info["period"]) & (bl < t + length + 4 * info["period"])]
                at = float(bl[np.argmin(np.abs(bl - (nominal_end - sec / 2)))]) if len(bl) else nominal_end - sec
                seg["end"] = round(at + sec, 4)
                switches.append({"at": round(at, 4), "type": "fade", "seconds": round(sec, 4), "reason": why})
                t = at
            else:
                seg["end"] = round(nominal_end, 4)
                switches.append({"at": round(nominal_end, 4), "type": "cut", "seconds": 0.0, "reason": why})
                t = nominal_end
        else:
            seg["end"] = round(nominal_end, 4)
            t = nominal_end
        segs.append(seg)
    duration = t
    # final fit: never exceed max, cut the last song on its own beat grid
    if duration > max_s + 1e-6:
        last = segs[-1]
        p = last["period"]
        keep = int((max_s - last["start"]) / p)
        last["end"] = round(last["start"] + keep * p, 4)
        duration = last["end"]
    for s in segs:
        s["src_out"] = round(s["src_in"] + (s["end"] - s["start"]), 4)
    return segs, switches, fit, round(duration, 4)
