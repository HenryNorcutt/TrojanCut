"""`autoplan P`: a heuristic edit plan from the brief, the footage index and the reference style.

Output length lands on the music's beat grid; cuts sit on the playing song's beats at about the
reference's shot length; every usable clip is used once before any repeats; transitions follow
effects_intensity; logo, title, colour grade, motion effects and sound effects follow the brief.
"""
import math
import re
from pathlib import Path

import numpy as np

import music as music_mod
import sfx as sfx_mod
from common import SKILL_DIR, fail, load_brief, output_size, project_dir, read_json, write_json

SOFT_TYPES = ["fade", "smoothleft", "fadewhite", "slideup", "circleopen", "wipeleft", "zoomin", "smoothup"]
SOFT_EVERY = {"low": 8, "medium": 3, "high": 2}
FX_SCALE = {"low": 0.5, "medium": 1.0, "high": 1.5}
FX_DEFAULT_PER_10S = {"flash": 0.3, "shake": 0.3, "zoom": 0.5, "ramp": 0.3}
FX_WORDS = {"flash": r"flash", "shake": r"shake|shaky", "zoom": r"zoom|punch", "ramp": r"ramp|slow[- ]?mo|speed"}


def clip_matches(path, words):
    name = Path(path).name.lower()
    return any(str(w).strip().lower() and str(w).strip().lower() in name for w in words or [])


# ---------------------------------------------------------------- music

def resolve_music(brief, idx, style, proj, fallback_period):
    """List of song dicts (file, info, part), or [] when the edit uses clip audio."""
    m = brief["music"]
    if isinstance(m, str) and m.strip().lower() in ("", "none"):
        return [], "none"
    if isinstance(m, str) and m.strip().lower() == "reference":
        refs = [r for r in idx["refs"] if r.get("has_audio")]
        if not refs:
            fail("music is 'reference audio' but no reference video has a soundtrack")
        lead = max(refs, key=lambda r: r["duration"])
        return [{"file": lead["path"], "part": "auto"}], "reference"
    items = m if isinstance(m, list) else [m]
    songs = []
    for it in items:
        if isinstance(it, dict):
            f, part = it.get("file"), it.get("part", "auto")
        else:
            f, part = it, "auto"
        if not f:
            fail("brief.yaml music entry has no file")
        if not (proj / f).exists():
            fail(f"music file not found: {f}")
        if not (part == "auto" or (isinstance(part, (list, tuple)) and len(part) == 2)):
            fail(f"music part for {f} must be 'auto' or [start, end], got {part!r}")
        songs.append({"file": f, "part": part})
    return songs, "songs"


def song_infos(songs, proj, fallback_period):
    cache = {}
    for s in songs:
        if s["file"] not in cache:
            info = music_mod.analyze_song(proj / s["file"])
            if info["bpm"] <= 0 or info.get("confidence", 1) < 0.02:
                g = np.arange(0, info["duration"], fallback_period)
                info.update(bpm=round(60 / fallback_period, 2), period=fallback_period, beats=g, downbeat=0)
            cache[s["file"]] = info
        s["info"] = cache[s["file"]]
    return songs


def grid_beats(segs, duration):
    out = []
    for k, s in enumerate(segs):
        until = segs[k + 1]["start"] if k + 1 < len(segs) else duration
        for b in s["_beats"]:
            ot = s["start"] + (b - s["src_in"])
            if s["start"] - 1e-6 <= ot < until - 1e-6:
                out.append(round(float(ot), 4))
    return sorted(set(out))


# ---------------------------------------------------------------- shots

def choose_cuts(beats, duration, shot_len, first=None):
    """Cut times on the beat grid, each about shot_len after the last (the first at about `first`)."""
    beats = [b for b in beats if 0.05 < b < duration - 0.05]
    cuts, c = [], 0.0
    if first and beats:
        b0 = min(beats, key=lambda b: abs(b - first))
        if duration - b0 > shot_len:
            cuts.append(b0)
            c = b0
    while True:
        cands = [b for b in beats if b > c + 0.45 * shot_len and b > c + 0.3]
        if not cands:
            break
        nxt = min(cands, key=lambda b: abs(b - c - shot_len))
        if duration - nxt < 0.5 * shot_len:
            break
        cuts.append(nxt)
        c = nxt
    return cuts


def order_clips(clips, brief):
    usable = [c for c in clips if c["duration"] >= 0.6 and not clip_matches(c["path"], brief["avoid"])]
    if not usable:
        fail("no usable clips in footage/ (every clip is shorter than 0.6 s or listed under avoid)")
    must = [c for c in usable if clip_matches(c["path"], brief["must_include"])]
    rest = sorted([c for c in usable if c not in must], key=lambda c: -c.get("motion", 0))
    return must + rest


def source_needed(length, keys):
    """Source seconds consumed by a shot of `length` output seconds under speed keys [{t, speed}]."""
    if not keys:
        return length
    ts = [0.0] + [k["t"] for k in keys] + [length]
    vs = [keys[0]["speed"]] + [k["speed"] for k in keys] + [keys[-1]["speed"]]
    total = 0.0
    for (t0, v0), (t1, v1) in zip(zip(ts, vs), zip(ts[1:], vs[1:])):
        a, b = max(0.0, min(t0, length)), max(0.0, min(t1, length))
        total += (b - a) * (v0 + v1) / 2
    return total


def assign(shots, clips):
    """Round-robin clips (each used once before repeats, never twice in a row); pick in points."""
    n = len(clips)
    cursor = {c["path"]: min(0.3, c["duration"] * 0.05) for c in clips}
    prev = None
    k = 0
    for s in shots:
        need = source_needed(s["end"] - s["start"], s.get("speed"))
        pad_in, pad_out = s.get("_handle_in", 0.0), s.get("_handle_out", 0.0)
        for attempt in range(n):
            c = clips[(k + attempt) % n]
            if c["path"] == prev and n > 1:
                continue
            if c["duration"] >= need + pad_in + pad_out + 0.05:
                break
        else:
            c = max(clips, key=lambda c: c["duration"])
        k = (clips.index(c) + 1) % n
        start = max(cursor[c["path"]], pad_in)
        if start + need + pad_out > c["duration"] - 0.02:
            start = max(pad_in, 0.0)
        if start + need + pad_out > c["duration"] - 0.02:
            start = max(0.0, c["duration"] - need - pad_out - 0.02)
        s["clip"] = c["path"]
        s["in"] = round(start, 3)
        s["out"] = round(start + need, 3)
        cursor[c["path"]] = start + need + 0.5
        if cursor[c["path"]] > c["duration"] - 1.0:
            cursor[c["path"]] = min(0.3, c["duration"] * 0.05)
        prev = c["path"]


# ---------------------------------------------------------------- motion effects

def fx_counts(style, duration, intensity, enabled):
    if not enabled:
        return {k: 0 for k in FX_DEFAULT_PER_10S}, {}
    pooled = style.get("motion", {})
    evidence = any(v.get("count", 0) for v in pooled.values())
    scale = FX_SCALE[intensity]
    counts = {}
    for k, default in FX_DEFAULT_PER_10S.items():
        if evidence:
            rate = pooled.get(k, {}).get("rate_per_10s", 0.0)
        else:
            rate = default if intensity != "low" else 0.0
        counts[k] = int(math.floor(rate * duration / 10 * scale + 0.5))
    return counts, pooled if evidence else {}


def place_fx(shots, beats, counts, pooled, period, width, soft_cuts):
    beats = np.array(beats)
    used = set()
    taken = []  # times of placed effects

    def free(t0, t1, gap=0.5):
        if any(min(abs(t0 - c), abs(t1 - c)) < 0.7 or t0 - 0.7 < c < t1 + 0.7 for c in soft_cuts):
            return False
        return all(t1 + gap <= a or t0 >= b + gap for a, b in taken)

    def beat_in(s, lo, hi, on_beat=True):
        cand = beats[(beats >= s["start"] + lo) & (beats <= s["end"] - hi)]
        if not on_beat:
            cand = cand + period / 2
            cand = cand[cand <= s["end"] - hi]
        return [float(b) for b in cand]

    def spread(n, pool):
        if n <= 0 or not pool:
            return []
        idx = sorted({int(round((i + 0.5) * len(pool) / n - 0.5)) for i in range(n)})
        return [pool[min(i, len(pool) - 1)] for i in idx]

    # ramps first: they need a long shot and no transitions at either edge
    nr = counts.get("ramp", 0)
    kind = "slow"
    for e in pooled.get("ramp", {}).get("events", []) if isinstance(pooled.get("ramp"), dict) else []:
        kind = e.get("kind", kind)
    cands = [i for i, s in enumerate(shots) if s["end"] - s["start"] >= max(1.0, 2 * period)
             and s["transition"]["type"] == "cut" and (i + 1 >= len(shots) or shots[i + 1]["transition"]["type"] == "cut")
             and i > 0]
    for i in spread(nr, cands):
        s = shots[i]
        L = s["end"] - s["start"]
        bts = [b - s["start"] for b in beat_in(s, 0.3, 0.3)]
        if not bts:
            continue
        mid = min(bts, key=lambda b: abs(b - L / 2))
        extreme = 0.3 if kind == "slow" else 2.5
        s["speed"] = [{"t": 0.0, "speed": 1.0}, {"t": round(mid, 4), "speed": extreme}, {"t": round(L, 4), "speed": 1.0}]
        used.add(i)
        taken.append((s["start"], s["end"]))

    for typ in ("zoom", "flash", "shake"):
        n = counts.get(typ, 0)
        info = pooled.get(typ, {}) if pooled else {}
        on_beat = info.get("on_beat_share", 1.0) >= 0.5 if info else True
        dur = {"flash": max(0.12, min(0.3, info.get("typical_duration", 0.15) or 0.15)),
               "zoom": max(0.35, min(0.6, (info.get("typical_duration", 0) or 0) + 0.3)),
               "shake": max(0.4, min(1.2, info.get("typical_duration", 0.6) or 0.6))}[typ]
        strength = {"flash": max(0.5, min(0.85, info.get("strength", 0.6) or 0.6)),
                    "zoom": max(0.15, min(0.35, info.get("strength", 0.2) or 0.2)),
                    "shake": max(0.012, min(0.04, info.get("strength", 0.02) or 0.02))}[typ]
        pool = [i for i in range(len(shots)) if i not in used and shots[i]["end"] - shots[i]["start"] >= dur + 0.5]
        placed = 0
        for i in spread(n, pool) + [p for p in pool]:
            if placed >= n:
                break
            if i in used:
                continue
            s = shots[i]
            times = [b for b in beat_in(s, 0.25, dur + 0.15, on_beat) if free(b, b + dur)]
            if not times:
                continue
            t = times[len(times) // 2]
            s.setdefault("effects", []).append({"type": typ, "at": round(t, 4), "duration": round(dur, 3),
                                                "strength": round(strength, 3)})
            used.add(i)
            taken.append((t, t + dur))
            placed += 1


# ---------------------------------------------------------------- main

def autoplan(proj):
    proj = project_dir(proj)
    brief = load_brief(proj)
    idx = read_json(proj / "work" / "index.json", "work/index.json (run ingest first)")
    style = read_json(proj / "work" / "style.json", "work/style.json (run analyze-refs first)")
    W, H = output_size(brief)
    fps = int(brief["fps"])
    min_s, max_s = brief["min_seconds"], brief["max_seconds"]
    clips = order_clips(idx["clips"], brief)
    total_footage = sum(c["duration"] for c in clips)
    target = min((min_s + max_s) / 2, max(min_s, 0.7 * total_footage))
    shot_len = max(0.4, float(style["median_shot_seconds"]))
    ref_period = 60.0 / style["bpm"] if style.get("bpm") else 0.5

    songs, mode = resolve_music(brief, idx, style, proj, ref_period)
    music_plan = {"mode": mode, "segments": [], "switches": [], "fit": "", "clip_audio_db": None}
    if songs:
        songs = song_infos(songs, proj, ref_period)
        segs, switches, fit, duration = music_mod.layout(songs, target, min_s, max_s, brief["song_switch"])
        info_by_file = {s["file"]: s["info"] for s in songs}
        for s in segs:
            s["_beats"] = info_by_file[s["file"]]["beats"]
        beats = grid_beats(segs, duration)
        if duration < min_s - 1e-3:
            fail(f"the music is too short for the brief: {duration:.1f}s of beats, need {min_s:g}s")
        for s in segs:
            del s["_beats"]
        music_plan.update(segments=segs, switches=switches, fit=fit)
        if brief["keep_clip_audio"]:
            music_plan["clip_audio_db"] = -12.0
    else:
        p = ref_period
        n = max(1, int(round(target / p)))
        while n * p > max_s + 1e-6 and n > 1:
            n -= 1
        while n * p < min_s - 1e-6:
            n += 1
        duration = n * p
        beats = [round(k * p, 4) for k in range(n)]
        music_plan.update(fit="no music: length on the reference's tempo", clip_audio_db=0.0)
    duration = round(duration, 4)
    if not (min_s - 0.01 <= duration <= max_s + 0.01):
        fail(f"could not fit the edit inside {min_s:g}-{max_s:g}s on the beat grid (got {duration:.2f}s)")

    period = float(np.median(np.diff(beats))) if len(beats) > 1 else ref_period
    text = str(brief.get("title_text") or "").strip()
    # the title plays over a held opening shot (one background behind the text), about 2 s or one shot
    cuts = choose_cuts(beats, duration, shot_len, first=max(shot_len, 2.0) if text else None)
    bounds = [0.0] + cuts + [duration]
    every = SOFT_EVERY[brief["effects_intensity"]]
    shots = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        tr = {"type": "cut", "duration": 0.0}
        if i > 0 and i % every == every - 1:
            d = round(min(0.4, 0.8 * period, (a - bounds[i - 1]) / 3, (b - a) / 3), 3)
            if d >= 0.12:
                tr = {"type": SOFT_TYPES[(i // every) % len(SOFT_TYPES)], "duration": d}
        shots.append({"start": round(a, 4), "end": round(b, 4), "transition": tr})
    for i, s in enumerate(shots):
        s["_handle_in"] = s["transition"]["duration"] / 2
        s["_handle_out"] = shots[i + 1]["transition"]["duration"] / 2 if i + 1 < len(shots) else 0.0

    match = brief["match"]
    notes = str(brief.get("notes") or "")
    fx_on = match == "full" or any(re.search(p, notes, re.I) for p in FX_WORDS.values())
    counts, pooled = fx_counts(style, duration, brief["effects_intensity"], fx_on)
    if not match == "full":
        counts = {k: (v if re.search(FX_WORDS[k], notes, re.I) else 0) for k, v in counts.items()}
        if any(counts.values()) is False and fx_on:
            counts = {k: (1 if re.search(FX_WORDS[k], notes, re.I) else 0) for k in counts}
    soft_cuts = [s["start"] for s in shots if s["transition"]["type"] != "cut"]
    place_fx(shots, beats, counts, pooled, period, W, soft_cuts)
    assign(shots, clips)
    for s in shots:
        s.pop("_handle_in", None)
        s.pop("_handle_out", None)

    grade = None
    if match in ("full", "color"):
        grade = {"lut": style["lut"], "strength": 1.0}
    logo = None
    if brief.get("logo") and brief.get("logo_position", "none") != "none":
        if not (proj / brief["logo"]).exists():
            fail(f"logo file not found: {brief['logo']}")
        logo = {"file": brief["logo"], "position": brief["logo_position"], "size": 0.14}
    title = None
    if text:
        end = bounds[1]
        title = {"text": text, "start": 0.0, "end": round(end, 4), "color": style.get("text_color", "#ffffff"),
                 "animation": "pop"}

    plan = {"version": 1, "width": W, "height": H, "fps": fps, "aspect": brief["aspect"], "duration": duration,
            "effects_intensity": brief["effects_intensity"], "match": match, "beats": beats, "shots": shots,
            "music": music_plan, "grade": grade, "logo": logo, "title": title, "sfx": [],
            "notes": notes}
    plan["sfx"] = sfx_mod.place(plan, brief, idx, proj)
    write_json(proj / "work" / "plan.json", plan)
    n_fx = sum(len(s.get("effects", [])) + (1 if s.get("speed") else 0) for s in shots)
    print(f"planned {len(shots)} shots over {duration:.2f}s ({len(cuts)} cuts, {len(soft_cuts)} soft transitions, "
          f"{n_fx} motion effects, {len(plan['sfx'])} sound effects) -> work/plan.json")
