"""`analyze-refs P`: what to copy from the reference videos.

Per reference: hard-cut times (ffmpeg scene score), median shot length, tempo and beat grid (from
its own audio, else from the brief's music), colour statistics and a .cube LUT that moves the
footage's colour toward it, plus a few deduplicated scene frames for Claude to look at.

Scene-frame sampling and near-duplicate removal are adapted from bradautomates/claude-video
(skills/watch/scripts/frames.py, MIT; see THIRD_PARTY_NOTICES.md).
"""
import json
import math
import re
import shutil
import statistics
import subprocess
from pathlib import Path

import numpy as np

import audio
import motion
from common import fail, load_brief, log, project_dir, read_json, rel, write_json

SCENE_THRESHOLD = 0.15         # ffmpeg scene score for a hard cut
STYLE_IMAGE_BUDGET = 12        # of the 40 shared with index.json
FRAME_RES = 512                # longest side of scene frames for Claude
DEDUP_THUMB = 16               # claude-video: 16x16 RGB thumbnails
DEDUP_THRESHOLD = 12.0         # mean abs diff (0-255); higher than claude-video's 2.0 since cuts here are
                               # between distinct shots and Claude needs only one frame per look
LUT_SIZE = 17
SHOWINFO_TS_RE = re.compile(r"pts_time:([^\s]+)")


# ---------------------------------------------------------------- cuts

def detect_cuts(path, w=160, h=90):
    """Hard-cut times: ffmpeg scene score above threshold, merged when closer than 0.2 s."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-i", str(path), "-an", "-vf",
                        f"scale={w}:{h},select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    times = [float(m.group(1)) for m in SHOWINFO_TS_RE.finditer(r.stderr)]
    out = []
    for t in times:
        if t > 0.05 and (not out or t - out[-1] >= 0.2):
            out.append(round(t, 3))
    return out


def shot_lengths(cuts, dur):
    bounds = [0.0] + cuts + [dur]
    lens = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]
    # the first/last shots are often clipped by the start/end of the reference; use inner shots when possible
    inner = lens[1:-1] if len(lens) >= 4 else lens
    return lens, inner


# ---------------------------------------------------------------- colour

def sample_rgb(path, dur, n=24, size=48):
    if dur <= 0:
        return np.zeros((0, 3))
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                        f"fps={n / dur:.6f},scale={size}:{size}:flags=area,format=rgb24", "-frames:v", str(n),
                        "-f", "rawvideo", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, 3).astype(np.float64)


def colour_summary(px):
    if not len(px):
        return {"mean_rgb": [128, 128, 128], "std_rgb": [50, 50, 50], "luma": 128, "saturation": 0}
    mean, std = px.mean(0), px.std(0)
    luma = float((px @ np.array([0.2126, 0.7152, 0.0722])).mean())
    mx, mn = px.max(1), px.min(1)
    sat = float(np.mean(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)))
    return {"mean_rgb": [round(float(v), 1) for v in mean], "std_rgb": [round(float(v), 1) for v in std],
            "luma": round(luma, 1), "saturation": round(sat, 3)}


def write_lut(path, src, dst, strength=1.0, title="trojancut"):
    """Per-channel mean/std transfer from src stats to dst stats as a 3D .cube (red index fastest)."""
    sm, ss = np.array(src["mean_rgb"]) / 255, np.maximum(np.array(src["std_rgb"]) / 255, 0.02)
    dm, ds = np.array(dst["mean_rgb"]) / 255, np.maximum(np.array(dst["std_rgb"]) / 255, 0.02)
    gain = np.clip(ds / ss, 0.5, 2.0)
    g = np.linspace(0, 1, LUT_SIZE)
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {LUT_SIZE}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    for b in g:
        for gg in g:
            for r in g:
                v = np.array([r, gg, b])
                t = np.clip((v - sm) * gain + dm, 0, 1)
                # protect highlights: near-white stays white (titles, sky, logos keep their brightness)
                protect = np.clip((v.min() - 0.85) / 0.15, 0, 1)
                o = np.clip(v + strength * (1 - protect) * (t - v), 0, 1)
                lines.append(f"{o[0]:.5f} {o[1]:.5f} {o[2]:.5f}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- frames for Claude (claude-video)

def extract_scene_frames(path, out_dir, prefix):
    """First frame plus one frame per scene change, scaled to FRAME_RES (claude-video
    extract_scene_candidates, threshold matched to our cut detector)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / f"{prefix}_%04d.jpg"
    scale = (f"scale=w='min({FRAME_RES},iw)':h='min({FRAME_RES},ih)':force_original_aspect_ratio=decrease:"
             "force_divisible_by=2")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "info", "-y", "-i", str(path), "-an", "-vf",
                        f"select='eq(n\\,0)+gt(scene\\,{SCENE_THRESHOLD})',{scale},showinfo", "-fps_mode", "vfr",
                        "-q:v", "4", str(pattern)], capture_output=True, text=True)
    files = sorted(out_dir.glob(f"{prefix}_*.jpg"))
    stamps = [float(m.group(1)) for m in SHOWINFO_TS_RE.finditer(r.stderr)]
    return [{"path": f, "t": round(stamps[i], 3) if i < len(stamps) else None} for i, f in enumerate(files)]


def thumbs(paths):
    """16x16 RGB thumbnails via one ffmpeg pass per file (claude-video _thumb_frames, per-file variant)."""
    out = []
    for p in paths:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf",
                            f"scale={DEDUP_THUMB}:{DEDUP_THUMB},format=rgb24", "-f", "rawvideo", "-"],
                           capture_output=True)
        out.append(np.frombuffer(r.stdout, np.uint8).astype(np.float64))
    return out


def dedupe(cands, threshold=DEDUP_THRESHOLD):
    """Drop frames within `threshold` mean abs difference of ANY kept frame (claude-video's
    _dedupe_by_deltas compares only to the last kept; references cycling a few looks need all)."""
    if len(cands) <= 1:
        return cands
    th = thumbs([c["path"] for c in cands])
    kept, kept_th = [], []
    for c, t in zip(cands, th):
        if len(t) and any(len(k) == len(t) and np.abs(t - k).mean() <= threshold for k in kept_th):
            c["path"].unlink(missing_ok=True)
            continue
        kept.append(c)
        kept_th.append(t)
    return kept


def even_sample(items, n):
    """claude-video _even_indices: n evenly spaced items, first and last kept."""
    if n >= len(items):
        return items
    if n <= 1:
        return items[:1]
    idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in idx]


# ---------------------------------------------------------------- main

def music_track(brief, idx, proj):
    """Path of the brief's first song (for silent references), if any."""
    m = brief.get("music")
    if isinstance(m, list) and m:
        m = m[0].get("file") if isinstance(m[0], dict) else m[0]
    if isinstance(m, str) and m not in ("", "none", "reference"):
        p = proj / m
        if p.exists():
            return p
    return None


def analyze_refs(proj):
    proj = project_dir(proj)
    brief = load_brief(proj)
    idx = read_json(proj / "work" / "index.json", "work/index.json (run ingest first)")
    if not idx.get("refs"):
        fail("no reference videos found in refs/ - add at least one video to copy the style from")
    work = proj / "work"
    fdir = work / "frames"
    if fdir.exists():
        shutil.rmtree(fdir)
    (work / "luts").mkdir(parents=True, exist_ok=True)

    clip_px = [sample_rgb(proj / c["path"], c["duration"], n=6) for c in idx["clips"][:40]]
    clip_px = np.concatenate(clip_px) if clip_px else np.zeros((0, 3))
    src_colour = colour_summary(clip_px)

    song = music_track(brief, idx, proj)
    song_grid = None
    refs, all_frames, all_px = [], [], []
    for k, r in enumerate(idx["refs"]):
        path = proj / r["path"]
        dur = r["duration"]
        cuts = detect_cuts(path)
        if r.get("has_audio"):
            x = audio.decode(path)
            grid = audio.beat_track(x)
            src = "reference"
        else:
            grid = None
            src = None
        if not grid or grid["bpm"] <= 0 or grid["confidence"] < 0.05:
            if song is not None:
                if song_grid is None:
                    song_grid = audio.beat_track(audio.decode(song))
                grid, src = song_grid, "music"
        # motion effects; scene "cuts" that are really flashes or zoom punches are not cuts
        mfx, false_cuts = motion.analyze(path, cuts, grid["beats"] if grid else [])
        cuts = [c for c in cuts if c not in false_cuts]
        lens, inner = shot_lengths(cuts, dur)
        median = statistics.median(inner) if inner else dur
        if not grid or grid["bpm"] <= 0:
            grid, src = audio.grid_from_period(60 / audio.bpm_from_shot(median), dur), "cuts"
            for k in mfx.values():
                k["on_beat_share"] = 0.0
        px = sample_rgb(path, dur)
        all_px.append(px)
        colour = colour_summary(px)
        lut = work / "luts" / f"ref{k + 1}.cube"
        write_lut(lut, src_colour, colour, title=Path(r["path"]).stem)
        frames = extract_scene_frames(path, fdir, f"ref{k + 1}")
        frames = dedupe(frames)
        all_frames.append(frames)
        beats = grid["beats"]
        refs.append({"path": r["path"], "duration": dur, "cuts": cuts, "shots": len(lens),
                     "median_shot_seconds": round(median, 3), "bpm": grid["bpm"], "beat_source": src,
                     "beats": beats, "downbeat": grid.get("downbeat", 0), "color": colour, "lut": rel(lut, proj),
                     "motion": mfx})

    # Claude's frames: share the budget across references, then dedupe across all of them.
    per = max(1, STYLE_IMAGE_BUDGET // len(all_frames))
    chosen = []
    for frames in all_frames:
        chosen += even_sample(frames, per)
    chosen = dedupe(chosen)[:STYLE_IMAGE_BUDGET]
    keep = {c["path"] for c in chosen}
    for frames in all_frames:
        for f in frames:
            if f["path"] not in keep:
                f["path"].unlink(missing_ok=True)
    for r, frames in zip(refs, all_frames):
        r["frames"] = [{"path": rel(f["path"], proj), "t": f["t"]} for f in frames if f["path"] in keep]

    # Overall style: the longest reference leads tempo and pace; colour pools all references.
    lead = max(refs, key=lambda r: r["duration"])
    pooled = colour_summary(np.concatenate(all_px)) if all_px else src_colour
    lut_all = work / "luts" / "style.cube"
    write_lut(lut_all, src_colour, pooled, title="style")
    bright = pooled["luma"] < 140
    style = {
        "version": 1,
        "median_shot_seconds": round(statistics.median([r["median_shot_seconds"] for r in refs]), 3),
        "bpm": lead["bpm"], "beat_source": lead["beat_source"],
        "color": pooled, "source_color": src_colour, "lut": rel(lut_all, proj),
        "text_color": "#ffffff" if bright else "#111111",
        "motion": pooled_motion(refs),
        "refs": refs,
        "claude_images": [rel(c["path"], proj) for c in chosen],
    }
    shrink_to_budget(proj, style, idx)
    write_json(work / "style.json", style, compact=True)
    print(f"analysed {len(refs)} reference(s): median shot {style['median_shot_seconds']}s, "
          f"{style['bpm']} BPM ({style['beat_source']}), {len(style['claude_images'])} frames -> work/style.json")


def pooled_motion(refs):
    """Rate per 10 s, typical duration/strength and on-beat share of each effect over all references."""
    total = sum(r["duration"] for r in refs) or 1.0
    out = {}
    for k in ("flash", "shake", "zoom", "ramp"):
        ev = [e for r in refs for e in r["motion"][k]["events"]]
        n_on = sum(r["motion"][k]["on_beat_share"] * len(r["motion"][k]["events"]) for r in refs)
        out[k] = {"count": len(ev), "rate_per_10s": round(10 * len(ev) / total, 2),
                  "typical_duration": round(statistics.median([e["duration"] for e in ev]), 3) if ev else 0.0,
                  "strength": round(statistics.median([e["strength"] for e in ev]), 3) if ev else 0.0,
                  "on_beat_share": round(n_on / len(ev), 2) if ev else 0.0}
    return out


TEXT_BUDGET = 60_000


def shrink_to_budget(proj, style, idx):
    """Keep index.json + style.json under 60 KB: move long arrays to work/detail/ sidecars."""
    def size():
        return len(json.dumps(style, separators=(",", ":"))) + (proj / "work" / "index.json").stat().st_size
    detail = proj / "work" / "detail"
    if size() <= TEXT_BUDGET:
        return
    detail.mkdir(exist_ok=True)
    for k, r in enumerate(style["refs"]):
        for m in r["motion"].values():
            if len(m["events"]) > 24:
                m["events_count"] = len(m["events"])
                m["events"] = m["events"][:24]
        for key in ("beats", "cuts"):
            if len(r[key]) > 64:
                side = detail / f"ref{k + 1}_{key}.json"
                side.write_text(json.dumps(r[key]))
                r[f"{key}_file"] = rel(side, proj)
                r[f"{key}_count"] = len(r[key])
                r[key] = r[key][:64]
    if size() > TEXT_BUDGET:
        fail(f"style.json + index.json exceed {TEXT_BUDGET} bytes even after trimming")


def full_list(proj, ref, key):
    """A reference's complete beats/cuts list, reading the sidecar when trimmed."""
    if ref.get(f"{key}_file"):
        return json.loads((Path(proj) / ref[f"{key}_file"]).read_text())
    return ref[key]
