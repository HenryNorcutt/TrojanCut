"""`render P`: plan.json -> out/final.mp4.

Both engines share the ffmpeg stages:
  1. one graded, effected segment per shot (speed ramps, shake, zoom punch, flash, colour LUT),
  2. joined with hard cuts or xfade transitions,
  3. audio mix (music segments with cut/fade switches, clip audio, sound effects).
Then the text/logo layer is composited: HyperFrames renders an animated transparent overlay
(engine "hyperframes"); the ffmpeg engine overlays static Pillow-rendered PNGs.
"""
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

import engine as eng
from common import Fail, fail, ffmpeg, load_brief, log, media_info, project_dir, write_json
from sfx import resolve as sfx_path
from validate import validate

AR = 48000


def even(v):
    return int(round(v / 2) * 2)


# ---------------------------------------------------------------- per-shot video

def speed_expr(keys, L):
    """Knots (t, speed) of the piecewise-linear speed curve over a shot of length L."""
    ts = [0.0] + [k["t"] for k in keys] + [L]
    vs = [keys[0]["speed"]] + [k["speed"] for k in keys] + [keys[-1]["speed"]]
    knots = []
    for t, v in zip(ts, vs):
        t = min(max(t, 0.0), L)
        if knots and abs(knots[-1][0] - t) < 1e-6:
            knots[-1] = (t, v)
        else:
            knots.append((t, v))
    return knots


def source_time_fn(knots):
    """S(t): integral of piecewise-linear v from 0 to t (numpy, for building the frame map)."""
    def S(t):
        total = 0.0
        for (t0, v0), (t1, v1) in zip(knots, knots[1:]):
            if t <= t0:
                break
            b = min(t, t1)
            if t1 > t0:
                vb = v0 + (v1 - v0) * (b - t0) / (t1 - t0)
                total += (b - t0) * (v0 + vb) / 2
        return total
    return S


def fx_filters(shot, W, H, fps):
    """Shake / zoom / flash as ffmpeg filters on the W x H shot (times relative to the shot start)."""
    st = shot["start"]
    effects = shot.get("effects") or []
    zooms = [e for e in effects if e["type"] == "zoom"]
    shakes = [e for e in effects if e["type"] == "shake"]
    flashes = [e for e in effects if e["type"] == "flash"]
    out = []
    if zooms or shakes:
        # zoompan evaluates z/x/y per frame (crop's w/h would be fixed at the first frame). The window is
        # never larger than the frame (z >= margin >= 1) and x/y are clamped inside it: no black borders.
        zt = []
        for e in zooms:
            a, d, s = e["at"] - st, e["duration"], e["strength"]
            up = max(0.06, 0.25 * d)
            zt.append(f"if(between(it\\,{a:.4f}\\,{a + up:.4f})\\,{s:.4f}*sin(PI/2*(it-{a:.4f})/{up:.4f})\\,"
                      f"if(between(it\\,{a + up:.4f}\\,{a + d:.4f})\\,{s:.4f}*0.5*(1+cos(PI*(it-{a + up:.4f})/"
                      f"{d - up:.4f}))\\,0))")
        mag = max([e["strength"] for e in shakes] or [0])
        margin = 1.0 + 2.4 * mag + (0.01 if shakes else 0.0)
        z = f"{margin:.4f}*(1+" + ("+".join(zt) if zt else "0") + ")"
        jx, jy = [], []
        for k, e in enumerate(shakes):
            a, d = e["at"] - st, e["duration"]
            amp = e["strength"] * W
            env = f"between(it\\,{a:.4f}\\,{a + d:.4f})*sin(PI*(it-{a:.4f})/{d:.4f})"
            jx.append(f"{env}*{amp:.2f}*(sin(2*PI*11*it+{k})+0.5*sin(2*PI*17*it+{2 * k}))/1.5")
            jy.append(f"{env}*{amp * 0.8:.2f}*(sin(2*PI*13*it+{k + 1})+0.5*sin(2*PI*7*it+{k}))/1.5")
        sx = "+".join(jx) or "0"
        sy = "+".join(jy) or "0"
        x = f"max(0\\,min(iw-iw/zoom\\,iw/2-iw/zoom/2+({sx})))"
        y = f"max(0\\,min(ih-ih/zoom\\,ih/2-ih/zoom/2+({sy})))"
        out.append("setpts=PTS-STARTPTS")
        out.append(f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps}")
        out.append("setsar=1")
    for e in flashes:
        a, d, s = e["at"] - st, e["duration"], e["strength"]
        hold = 0.35 * d  # full white-ish for the first third, then a fast decay
        out.append(f"geq=lum='lum(X\\,Y)+(255-lum(X\\,Y))*{s:.3f}*if(between(T\\,{a:.4f}\\,{a + d:.4f})\\,"
                   f"if(lt(T-{a:.4f}\\,{hold:.4f})\\,1\\,exp(-4*(T-{a + hold:.4f})/{d - hold:.4f}))\\,0)':"
                   f"cb='cb(X\\,Y)':cr='cr(X\\,Y)'")
    return out


def render_shot(proj, plan, i, shot, out, lut, clips):
    W, H, fps = plan["width"], plan["height"], plan["fps"]
    tr_out = plan["shots"][i + 1]["transition"]["duration"] if i + 1 < len(plan["shots"]) else 0.0
    tr_in = shot["transition"]["duration"] if i > 0 else 0.0
    L = shot["end"] - shot["start"]
    # transitions overlap shots: each shot carries half the transition as a handle on each side
    pre, post = tr_in / 2, tr_out / 2
    total = L + pre + post
    c = clips[shot["clip"]]
    src = proj / shot["clip"]
    keys = shot.get("speed") or []
    filters = []
    if keys:
        # Speed ramp: output frame k shows the source frame nearest S(t_k), where S integrates the speed
        # curve. Frames are decoded once (scaled) and re-timed through a concat list; no interpolation.
        knots = speed_expr(keys, L)
        S = source_time_fn(knots)
        n_out = int(round(total * fps))
        v0, v1 = knots[0][1], knots[-1][1]
        times = []
        for k in range(n_out):
            t = k / fps - pre
            tc = min(max(t, 0.0), L)
            s_t = S(tc) + (t - tc) * (v0 if t < 0 else v1)
            times.append(max(0.0, shot["in"] + s_t))
        seek = max(0.0, min(times) - 0.2)
        span = max(times) - seek + 0.3
        sfps = c["fps"] or fps
        fdir = out.with_suffix("")
        fdir.mkdir(exist_ok=True)
        ffmpeg("-ss", f"{seek:.4f}", "-t", f"{span:.4f}", "-i", str(src), "-an", "-vf",
               f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,crop={W}:{H}",
               "-q:v", "2", str(fdir / "f%06d.jpg"))
        have = sorted(fdir.glob("f*.jpg"))
        if not have:
            fail(f"could not read frames from {shot['clip']} for a speed ramp")
        lst = out.with_suffix(".concat.txt")
        rows = []
        for tt in times:
            j = min(len(have) - 1, max(0, int(round((tt - seek) * sfps))))
            rows.append(f"file '{have[j].as_posix()}'\nduration {1 / fps:.6f}\n")
        rows.append(f"file '{have[min(len(have) - 1, max(0, int(round((times[-1] - seek) * sfps))))].as_posix()}'\n")
        lst.write_text("".join(rows))
        dec = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        filters.append(f"fps={fps}")
    else:
        start = max(0.0, shot["in"] - pre)
        dec = ["-ss", f"{start:.4f}", "-t", f"{total + 0.2:.4f}", "-i", str(src)]
        if shot["in"] - pre < 0:
            filters.append(f"tpad=start_duration={pre - shot['in']:.4f}:start_mode=clone")
        filters.append(f"fps={fps}")
    filters.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic")
    filters.append(f"crop={W}:{H}")
    filters.append("setsar=1")
    if lut:
        filters.append(f"lut3d=file='{lut_escape(lut)}'")
    filters += fx_filters(dict(shot, start=shot["start"] - pre), W, H, fps)
    filters.append(f"tpad=stop_mode=clone:stop_duration={total:.4f}")
    filters.append(f"trim=duration={total:.4f}")
    filters.append("format=yuv420p")
    ffmpeg(*dec, "-an", "-vf", ",".join(filters), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "16", "-g", str(fps), "-pix_fmt", "yuv420p", str(out))
    return total


def lut_escape(p):
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ---------------------------------------------------------------- join

def join_shots(parts, plan, out):
    """Concat with hard cuts; xfade where the plan has a transition."""
    fps = plan["fps"]
    shots = plan["shots"]
    if all(s["transition"]["type"] == "cut" for s in shots[1:]):
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p, _ in parts))
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))
        return
    inputs, chain = [], []
    for p, _ in parts:
        inputs += ["-i", str(p)]
    for i in range(len(parts)):
        chain.append(f"[{i}:v]fps={fps},setpts=PTS-STARTPTS,settb=AVTB[n{i}]")
    cur = "[n0]"
    acc = parts[0][1]
    for i in range(1, len(parts)):
        tr = shots[i]["transition"]
        d = tr["duration"]
        nxt = f"[n{i}]"
        lab = f"[v{i}]"
        if tr["type"] == "cut" or d <= 0:
            chain.append(f"{cur}{nxt}concat=n=2:v=1:a=0,settb=AVTB{lab}")
            acc += parts[i][1]
        else:
            off = acc - d
            chain.append(f"{cur}{nxt}xfade=transition={tr['type']}:duration={d:.4f}:offset={off:.4f},settb=AVTB{lab}")
            acc += parts[i][1] - d
        cur = lab
    chain.append(f"{cur}fps={fps},format=yuv420p[vout]")
    script = out.with_suffix(".filter")
    script.write_text(";\n".join(chain))
    ffmpeg(*inputs, "-filter_complex_script", str(script), "-map", "[vout]", "-c:v", "libx264", "-preset",
           "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(out))


# ---------------------------------------------------------------- audio

def build_audio(proj, plan, clips, out):
    dur = plan["duration"]
    m = plan.get("music") or {}
    inputs, chains, mix = [], [], []
    k = 0
    segs = m.get("segments") or []
    sw = {round(s["at"], 3): s for s in m.get("switches") or []}
    for j, s in enumerate(segs):
        length = s["end"] - s["start"]
        inputs += ["-ss", f"{s['src_in']:.4f}", "-t", f"{length + 0.05:.4f}", "-i", str(proj / s["file"])]
        f = [f"aresample={AR}", "aformat=channel_layouts=stereo", f"atrim=duration={length:.4f}", "asetpts=PTS-STARTPTS"]
        # fade in if the previous switch was a fade into this segment
        if j > 0:
            prev = m["switches"][j - 1]
            if prev["type"] == "fade":
                f.append(f"afade=t=in:d={prev['seconds']:.4f}:curve=qsin")
            else:
                f.append("afade=t=in:d=0.004")
        if j + 1 < len(segs):
            nxt = m["switches"][j]
            if nxt["type"] == "fade":
                f.append(f"afade=t=out:st={length - nxt['seconds']:.4f}:d={nxt['seconds']:.4f}:curve=qsin")
            else:
                f.append(f"afade=t=out:st={max(0.0, length - 0.004):.4f}:d=0.004")
        f.append(f"adelay={int(round(s['start'] * 1000))}|{int(round(s['start'] * 1000))}")
        chains.append(f"[{k}:a]{','.join(f)}[m{j}]")
        mix.append(f"[m{j}]")
        k += 1
    music_on = bool(segs)
    clip_db = m.get("clip_audio_db")
    if clip_db is not None:
        for i, s in enumerate(plan["shots"]):
            c = clips[s["clip"]]
            L = s["end"] - s["start"]
            if not c.get("has_audio") or s.get("speed"):
                continue
            inputs += ["-ss", f"{s['in']:.4f}", "-t", f"{L + 0.05:.4f}", "-i", str(proj / s["clip"])]
            ms = int(round(s["start"] * 1000))
            chains.append(f"[{k}:a]aresample={AR},aformat=channel_layouts=stereo,atrim=duration={L:.4f},"
                          f"asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st={max(0, L - 0.01):.4f}:d=0.01,"
                          f"volume={clip_db:.1f}dB,adelay={ms}|{ms}[c{i}]")
            mix.append(f"[c{i}]")
            k += 1
    for j, e in enumerate(plan.get("sfx") or []):
        inputs += ["-i", str(sfx_path(e["file"], proj))]
        ms = int(round(e["start"] * 1000))
        chains.append(f"[{k}:a]aresample={AR},aformat=channel_layouts=stereo,atrim=duration={e['duration']:.4f},"
                      f"volume={e.get('gain_db', -6):.1f}dB,adelay={ms}|{ms}[s{j}]")
        mix.append(f"[s{j}]")
        k += 1
    inputs += ["-f", "lavfi", "-t", f"{dur:.4f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
    mix.append(f"[{k}:a]")
    graph = ";".join(chains + [f"{''.join(mix)}amix=inputs={len(mix)}:duration=longest:normalize=0,"
                               f"atrim=duration={dur:.4f},alimiter=limit=0.89:level=false[aout]"])
    script = out.with_suffix(".filter")
    script.write_text(graph)
    ffmpeg(*inputs, "-filter_complex_script", str(script), "-map", "[aout]", "-c:a", "pcm_s16le", str(out))
    return music_on


# ---------------------------------------------------------------- overlays

POS = {"top-left": (0, 0), "top-right": (1, 0), "bottom-left": (0, 1), "bottom-right": (1, 1)}


def logo_box(plan):
    W, H = plan["width"], plan["height"]
    lg = plan["logo"]
    size = int(round(min(W, H) * lg.get("size", 0.14)))
    m = int(round(min(W, H) * 0.04))
    px, py = POS.get(lg["position"], (1, 0))
    x = m if px == 0 else W - m - size
    y = m if py == 0 else H - m - size
    return x, y, size


def font_path():
    cands = [os.environ.get("TROJANCUT_FONT", ""), "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    for c in cands:
        if c and Path(c).is_file():
            return c
    return None


def static_layers(proj, plan, tmp):
    """Pillow PNGs for the ffmpeg engine: (logo.png or None, title.png or None)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = plan["width"], plan["height"]
    logo_png = title_png = None
    if plan.get("logo"):
        x, y, size = logo_box(plan)
        im = Image.open(proj / plan["logo"]["file"]).convert("RGBA")
        im.thumbnail((size, size))
        logo_png = tmp / "logo.png"
        im.save(logo_png)
    if plan.get("title"):
        t = plan["title"]
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fp = font_path()
        size = int(min(W, H) * 0.12)
        text = t["text"]
        while True:
            font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default(size=size)
            box = d.textbbox((0, 0), text, font=font)
            if box[2] - box[0] <= W * 0.86 or size <= 12:
                break
            size = int(size * 0.9)
        tw, th = box[2] - box[0], box[3] - box[1]
        x, y = (W - tw) // 2 - box[0], (H - th) // 2 - box[1]
        col = t.get("color", "#ffffff")
        shadow = (0, 0, 0, 170) if col.lower() in ("#ffffff", "#fff", "white") else (255, 255, 255, 170)
        off = max(2, size // 24)
        d.text((x + off, y + off), text, font=font, fill=shadow)
        d.text((x, y), text, font=font, fill=col)
        title_png = tmp / "title.png"
        img.save(title_png)
    return logo_png, title_png


def composite_static(base, logo_png, title_png, plan, out):
    inputs = ["-i", str(base)]
    chain = []
    cur = "[0:v]"
    k = 1
    if title_png:
        t = plan["title"]
        inputs += ["-i", str(title_png)]
        chain.append(f"{cur}[{k}:v]overlay=0:0:enable='between(t\\,{t['start']:.3f}\\,{t['end']:.3f})'[t]")
        cur = "[t]"
        k += 1
    if logo_png:
        x, y, size = logo_box(plan)
        inputs += ["-i", str(logo_png)]
        chain.append(f"{cur}[{k}:v]overlay={x}:{y}[l]")
        cur = "[l]"
        k += 1
    chain.append(f"{cur}format=yuv420p[vout]")
    ffmpeg(*inputs, "-filter_complex", ";".join(chain), "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "18", "-pix_fmt", "yuv420p", str(out))


def composite_overlay(base, frames_dir, plan, out):
    fps = plan["fps"]
    ffmpeg("-i", str(base), "-framerate", str(fps), "-i", str(frames_dir / "frame_%06d.png"), "-filter_complex",
           "[0:v][1:v]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[vout]", "-map", "[vout]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out))


# ---------------------------------------------------------------- main

def render(proj):
    proj = project_dir(proj)
    t0 = time.time()
    plan = validate(proj)
    idx = json.loads((proj / "work" / "index.json").read_text())
    clips = {c["path"]: c for c in idx["clips"]}
    engine, fallback = eng.choose_engine()
    tmp = proj / "work" / "render"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    (proj / "out").mkdir(exist_ok=True)
    lut = (proj / plan["grade"]["lut"]) if plan.get("grade") else None
    if lut and plan["grade"].get("strength", 1.0) < 0.999:
        lut = blend_lut(lut, plan["grade"]["strength"], tmp / "grade.cube")
    parts = []
    for i, s in enumerate(plan["shots"]):
        p = tmp / f"shot{i:03d}.mp4"
        parts.append((p, render_shot(proj, plan, i, s, p, lut, clips)))
    base = tmp / "base.mp4"
    join_shots(parts, plan, base)
    log(f"video base rendered ({len(parts)} shots)")
    wav = tmp / "mix.wav"
    build_audio(proj, plan, clips, wav)
    layered = tmp / "layered.mp4"
    layers = {"title": None, "logo": None}
    if plan.get("title") or plan.get("logo"):
        done = False
        if engine == "hyperframes":
            import hf
            try:
                frames = hf.render_overlay(proj, plan, tmp / "hf")
                composite_overlay(base, frames, plan, layered)
                done = True
                layers = {"title": "hyperframes" if plan.get("title") else None,
                          "logo": "hyperframes" if plan.get("logo") else None}
            except Fail as e:
                engine, fallback = "ffmpeg", f"HyperFrames render failed: {e}"
                log(f"falling back to the ffmpeg engine: {e}")
        if not done:
            logo_png, title_png = static_layers(proj, plan, tmp)
            composite_static(base, logo_png, title_png, plan, layered)
            layers = {"title": "ffmpeg" if plan.get("title") else None, "logo": "ffmpeg" if plan.get("logo") else None}
    else:
        shutil.copyfile(base, layered)
    final = proj / "out" / "final.mp4"
    ffmpeg("-i", str(layered), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
           "-b:a", "192k", "-t", f"{plan['duration']:.4f}", "-movflags", "+faststart", str(final))
    info = {"engine": engine, "fallback_reason": fallback, "layers": layers,
            "render_seconds": round(time.time() - t0, 1), "music_fit": (plan.get("music") or {}).get("fit", ""),
            "sfx_count": len(plan.get("sfx") or [])}
    write_json(proj / "work" / "render.json", info)
    if os.environ.get("TROJANCUT_KEEP_RENDER") != "1":
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"rendered out/final.mp4 with the {engine} engine in {info['render_seconds']}s"
          + (f" ({fallback})" if fallback and engine == "ffmpeg" else ""))


def blend_lut(lut, strength, out):
    lines = Path(lut).read_text().splitlines()
    size = int(next(l.split()[1] for l in lines if l.startswith("LUT_3D_SIZE")))
    g = np.linspace(0, 1, size)
    res, k = [], 0
    for l in lines:
        if l and (l[0].isdigit() or l[0] in "-."):
            b, gg, r = k // (size * size), (k // size) % size, k % size
            v = np.array(list(map(float, l.split())))
            o = np.array([g[r], g[gg], g[b]]) * (1 - strength) + v * strength
            res.append(f"{o[0]:.5f} {o[1]:.5f} {o[2]:.5f}")
            k += 1
        else:
            res.append(l)
    Path(out).write_text("\n".join(res) + "\n")
    return out
