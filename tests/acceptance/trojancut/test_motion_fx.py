"""D11: AB18 motion effects (flash, shake, zoom punch, speed ramp): detection, planning, render, validate."""
import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from _helpers import engine_env, ff, frame, load, make_clip, make_song, probe, run_pipeline, save_plan, tc, write_brief

FPS = 25
W, H = 320, 180
TYPES = ("flash", "shake", "zoom", "ramp")


# ---------------------------------------------------------------- synthetic references

TEXTURE = ("geq=r='clip({r}+50*sin(X/9)*cos(Y/7)+30*(mod(floor(X/40)+floor(Y/40)\\,2))\\,0\\,225)':"
           "g='clip({g}+45*sin(X/13+Y/11)\\,0\\,225)':b='clip({b}+50*cos(X/17)*sin(Y/5)\\,0\\,225)'")


def texture(tint=(128, 110, 100)):
    r, g, b = tint
    return TEXTURE.format(r=r, g=g, b=b)


def textured(path, seconds, w=W, h=H, fps=FPS, pan=None, zoom=None):
    """A static textured scene on a 2x canvas, viewed through a moving crop (pan=(x_expr, y_expr), per-frame)
    or a zoompan (zoom=z_expr of `it`, centred)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cw, ch = w * 2, h * 2
    if zoom:
        view = (f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}")
        base = f"[0:v]format=rgb24,{texture()},scale={w}:{h},scale={cw}:{ch},{view}"
    else:
        xe, ye = pan or (f"{cw // 4}", f"{ch // 4}")
        base = f"[0:v]format=rgb24,{texture()},crop=w={w}:h={h}:x='{xe}':y='{ye}':exact=1"
    ff("-f", "lavfi", "-i", f"color=c=gray:s={cw}x{ch}:r={fps}:d={seconds}", "-filter_complex",
       base + ",format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", str(fps), path)


def footage_clip(path, tint, dur=10, w=W, h=H, fps=FPS):
    """Textured, tinted footage (static camera) with the overlay-based moving white box (106 px/s)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    bw = w // 8
    ff("-f", "lavfi", "-i", f"color=c=gray:s={w}x{h}:r={fps}:d={dur}",
       "-f", "lavfi", "-i", f"color=c=white:s={bw}x{bw}:r={fps}:d={dur}",
       "-filter_complex", f"[0:v]format=rgb24,{texture(tint)}[bg];"
       f"[bg][1:v]overlay=x='mod(t*{w // 3},{w - bw})':y={h // 3}:shortest=1,format=yuv420p[v]",
       "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", str(fps), path)


def add_flashes(src, dst, times, dur=0.12):
    en = "+".join(f"between(t\\,{t:.3f}\\,{t + dur:.3f})" for t in times)
    ff("-i", src, "-vf", f"eq=brightness=0.6:enable='{en}'", "-c:v", "libx264", "-pix_fmt", "yuv420p", dst)


def pan_expr(cw, rate):
    return f"mod(t*{rate}\\,{cw // 2})"


@pytest.fixture(scope="module")
def refs(tmp_path_factory):
    d = tmp_path_factory.mktemp("refs")
    cw, ch = W * 2, H * 2
    out = {}
    # clean: slow steady pan, no events
    textured(d / "clean.mp4", 10, pan=(pan_expr(cw, 20), f"{ch // 4}"))
    out["clean"] = d / "clean.mp4"
    # flashes at known times on the clean pan
    out["flash_times"] = [2.0, 4.5, 7.0]
    add_flashes(d / "clean.mp4", d / "flash.mp4", out["flash_times"])
    out["flash"] = d / "flash.mp4"
    # shake: +-12 px jitter at 12 Hz in windows [3,4] and [6.5,7.3]
    win = "(between(t\\,3\\,4)+between(t\\,6.5\\,7.3))"
    jit = f"{win}*12*sin(2*PI*12*t)"
    jit_y = f"{win}*9*sin(2*PI*9*t+1)"
    textured(d / "shake.mp4", 10, pan=(f"{cw // 4}+{jit}", f"{ch // 4}+{jit_y}"))
    out["shake"] = d / "shake.mp4"
    out["shake_windows"] = [(3.0, 4.0), (6.5, 7.3)]
    # zoom punches: 1 -> 1.35 over 0.12 s then settle back over 0.4 s, at 2.5 and 6.0
    def punch(t0):
        return (f"if(between(it\\,{t0}\\,{t0 + 0.12})\\,0.35*(it-{t0})/0.12\\,"
                f"if(between(it\\,{t0 + 0.12}\\,{t0 + 0.52})\\,0.35*(1-(it-{t0 + 0.12})/0.4)\\,0))")
    out["zoom_times"] = [2.5, 6.0]
    textured(d / "zoom.mp4", 9, zoom=f"1+{punch(2.5)}+{punch(6.0)}")
    out["zoom"] = d / "zoom.mp4"
    # speed ramp in one shot: pan 60 px/s, 300 px/s in [4,5.5], back to 60
    x = f"60*t+240*(clip(t\\,4\\,5.5)-4)"
    textured(d / "ramp.mp4", 9, pan=(f"mod({x}\\,{cw // 2})", f"{ch // 4}"))
    out["ramp"] = d / "ramp.mp4"
    out["ramp_window"] = (4.0, 5.5)
    return out


def analyze_one(tmp_path, ref, name):
    proj = tmp_path / name
    make_clip(proj / "footage" / "a.mp4", "304050", w=W, h=H, dur=4)
    (proj / "refs").mkdir(parents=True, exist_ok=True)
    (proj / "refs" / "ref.mp4").write_bytes(Path(ref).read_bytes())
    make_song(proj / "music" / "s.wav", 120, 20, 440)
    write_brief(proj, music="music/s.wav", logo="", title_text="", sfx_amount="none")
    tc("ingest", proj)
    tc("analyze-refs", proj)
    style = json.loads((proj / "work" / "style.json").read_text())
    return style, style["refs"][0]["motion"]


def events(m, kind):
    return [e["t"] for e in m[kind]["events"]]


def test_style_schema_and_clean_reference(refs, tmp_path):
    style, m = analyze_one(tmp_path, refs["clean"], "clean")
    for k in TYPES:
        assert k in m, m.keys()
        for f in ("events", "rate_per_10s", "typical_duration", "strength", "on_beat_share"):
            assert f in m[k], (k, f)
        assert m[k]["events"] == [], f"clean reference reported {k}: {m[k]['events']}"
    assert "motion" in style


def test_detect_flashes(refs, tmp_path):
    style, m = analyze_one(tmp_path, refs["flash"], "flash")
    got = events(m, "flash")
    assert len(got) == len(refs["flash_times"]), got
    for t in refs["flash_times"]:
        assert min(abs(t - g) for g in got) <= 0.1, (t, got)
    assert m["flash"]["rate_per_10s"] == pytest.approx(3.0, abs=0.5)
    for k in ("shake", "zoom", "ramp"):
        assert m[k]["events"] == [], (k, m[k]["events"])


def test_detect_shake(refs, tmp_path):
    style, m = analyze_one(tmp_path, refs["shake"], "shake")
    got = m["shake"]["events"]
    assert len(got) == 2, got
    for (a, b), e in zip(refs["shake_windows"], sorted(got, key=lambda e: e["t"])):
        assert abs(e["t"] - a) <= 0.1, (e, a)
        assert abs(e["duration"] - (b - a)) <= 0.25, (e, a, b)
    assert m["flash"]["events"] == [] and m["zoom"]["events"] == []


def test_detect_zoom(refs, tmp_path):
    style, m = analyze_one(tmp_path, refs["zoom"], "zoom")
    got = events(m, "zoom")
    assert len(got) == 2, got
    for t in refs["zoom_times"]:
        assert min(abs(t - g) for g in got) <= 0.1, (t, got)
    assert m["flash"]["events"] == [] and m["shake"]["events"] == []


def test_detect_ramp(refs, tmp_path):
    style, m = analyze_one(tmp_path, refs["ramp"], "ramp")
    got = events(m, "ramp")
    assert len(got) >= 1, got
    a, b = refs["ramp_window"]
    assert any(abs(g - a) <= 0.1 or abs(g - b) <= 0.1 for g in got), got
    assert m["flash"]["events"] == [] and m["shake"]["events"] == []


# ---------------------------------------------------------------- planning + render

def mfx_project(root, refs, intensity="high", ref_key="flash", ramp_clip=True):
    root = Path(root)
    tints = [(170, 40, 40), (40, 150, 50), (160, 150, 30), (50, 90, 170)]
    for i, t in enumerate(tints):
        footage_clip(root / "footage" / f"c{i}.mp4", t)
    (root / "refs").mkdir(parents=True, exist_ok=True)
    for k in ("flash", "shake", "zoom", "ramp"):
        (root / "refs" / f"{k}.mp4").write_bytes(Path(refs[k]).read_bytes())
    make_song(root / "music" / "s.wav", 120, 40, 440)
    write_brief(root, aspect="16:9", resolution=H, fps=FPS, music="music/s.wav", logo="", title_text="",
                match="full", effects_intensity=intensity, sfx_amount="none", min_seconds=14, max_seconds=18)
    run_pipeline(root, env=engine_env("ffmpeg"))
    return load(root, "plan.json"), load(root, "report.json")


@pytest.fixture(scope="module")
def rendered(refs, tmp_path_factory):
    root = tmp_path_factory.mktemp("mfx") / "p"
    plan, report = mfx_project(root, refs)
    return root, plan, report


def all_fx(plan, kind):
    out = []
    for s in plan["shots"]:
        for e in s.get("effects", []):
            if e["type"] == kind:
                out.append((s, e))
    return out


def test_plan_places_all_types(rendered):
    root, plan, report = rendered
    beats = np.array(plan["beats"])
    for kind in ("flash", "shake", "zoom"):
        fx = all_fx(plan, kind)
        assert fx, f"no {kind} placed"
        for s, e in fx:
            assert s["start"] - 1e-3 <= e["at"] and e["at"] + e["duration"] <= s["end"] + 1e-3
            assert e["strength"] > 0 and e["duration"] > 0
    ramps = [s for s in plan["shots"] if s.get("speed")]
    assert ramps, "no speed ramp placed"
    for s in ramps:
        keys = s["speed"]
        assert all(0.2 <= k["speed"] <= 4 for k in keys)
        slow = min(keys, key=lambda k: k["speed"]) if min(k["speed"] for k in keys) < 1 else \
            max(keys, key=lambda k: k["speed"])
        assert np.min(np.abs(beats - (s["start"] + slow["t"]))) <= 0.04, "ramp extreme not on a beat"


def test_effect_counts_scale_with_intensity(refs, tmp_path, rendered):
    root, plan_hi, _ = rendered
    plan_lo, _ = mfx_project(tmp_path / "lo", refs, intensity="low")
    n = lambda p: sum(len(s.get("effects", [])) + (1 if s.get("speed") else 0) for s in p["shots"])
    assert n(plan_lo) < n(plan_hi), (n(plan_lo), n(plan_hi))


def test_output_length_and_beat_grid_unchanged(rendered):
    root, plan, report = rendered
    dur = float(probe(root / "out" / "final.mp4")["format"]["duration"])
    assert abs(dur - plan["duration"]) < 0.1
    assert report["ok"] is True
    for a, b in zip(plan["shots"], plan["shots"][1:]):
        assert abs(a["end"] - b["start"]) < 1e-3


def mean_luma(img):
    return float((img * np.array([0.2126, 0.7152, 0.0722])).sum(2).mean())


def test_flash_luma_spikes(rendered):
    root, plan, report = rendered
    final = root / "out" / "final.mp4"
    for s, e in all_fx(plan, "flash"):
        peak = mean_luma(frame(final, e["at"] + 0.02, 80, 45))
        base_t = e["at"] + e["duration"] + 0.15 if e["at"] + e["duration"] + 0.2 < s["end"] else e["at"] - 0.15
        base = mean_luma(frame(final, base_t, 80, 45))
        assert peak > base + 25, (e, peak, base)


def no_black_border(img):
    edges = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    return float((edges.sum(1) < 30).mean()) < 0.02


def test_shake_and_zoom_never_black_borders(rendered):
    root, plan, report = rendered
    final = root / "out" / "final.mp4"
    for kind in ("shake", "zoom"):
        for s, e in all_fx(plan, kind):
            for t in np.linspace(e["at"] + 0.02, e["at"] + e["duration"] - 0.02, 5):
                assert no_black_border(frame(final, t, W, H)), (kind, t)


def test_shake_moves_only_in_window(rendered):
    root, plan, report = rendered
    final = root / "out" / "final.mp4"
    for s, e in all_fx(plan, "shake"):
        def jitter(t0, t1):
            fr = [frame(final, t, W, H).astype(np.float64).sum(2) for t in np.arange(t0, t1, 1 / FPS)]
            return np.mean([np.abs(a - b).mean() for a, b in zip(fr, fr[1:])])
        inside = jitter(e["at"] + 0.04, e["at"] + e["duration"] - 0.04)
        q0 = max(s["start"] + 0.05, e["at"] - 0.45)
        if e["at"] - q0 >= 0.2:
            outside = jitter(q0, e["at"] - 0.05)
            assert inside > 2 * outside + 1, (inside, outside)


def test_zoom_changes_scale(rendered):
    root, plan, report = rendered
    final = root / "out" / "final.mp4"
    for s, e in all_fx(plan, "zoom"):
        # the moving box (fully inside the frame vertically) looks taller at the punch peak than just before
        def box_width(t):
            img = frame(final, t, W, H)
            m = img.sum(2) > 3 * 235
            rows = np.where(m.any(1))[0]
            return (rows.max() - rows.min() + 1) if len(rows) else 0
        before = box_width(max(s["start"] + 0.04, e["at"] - 0.04))
        peak = max(box_width(e["at"] + d) for d in (0.08, 0.12, 0.16) if e["at"] + d < s["end"])
        assert before > 0 and peak >= before * 1.1, (before, peak, e)


def box_x(img):
    m = img.sum(2) > 3 * 235
    cols = np.where(m.any(0))[0]
    return float(cols.mean()) if len(cols) else None


def test_ramp_speed_follows_keyframes(rendered):
    """The moving box crosses at a known source speed; output speed must follow the speed curve."""
    root, plan, report = rendered
    final = root / "out" / "final.mp4"
    checked = 0
    for s in (s for s in plan["shots"] if s.get("speed")):
        keys = s["speed"]
        lo = min(keys, key=lambda k: k["speed"])
        hi = max(keys, key=lambda k: k["speed"])
        if hi["speed"] / lo["speed"] < 1.8:
            continue

        def vel(t):
            a, b = frame(final, t - 0.06, W, H), frame(final, t + 0.06, W, H)
            xa, xb = box_x(a), box_x(b)
            if xa is None or xb is None or abs(xb - xa) > W / 2:
                return None
            return abs(xb - xa) / 0.12
        v_lo = vel(s["start"] + lo["t"])
        v_hi = vel(s["start"] + hi["t"] + (0.08 if hi["t"] < 0.08 else -0.08 if hi["t"] > s["end"] - s["start"] - 0.08 else 0))
        if v_lo is None or v_hi is None or v_hi < 5:
            continue
        ratio = v_hi / max(v_lo, 1e-3)
        want = hi["speed"] / lo["speed"]
        assert ratio >= 0.5 * want, (ratio, want, keys)
        checked += 1
    assert checked >= 1, "no measurable ramp"


def test_validate_rejects_bad_motion(rendered):
    root, plan, report = rendered
    ramp_i = next(i for i, s in enumerate(plan["shots"]) if s.get("speed"))
    fx_i = next(i for i, s in enumerate(plan["shots"]) if s.get("effects"))

    def bad(mut, word):
        p = copy.deepcopy(plan)
        mut(p)
        save_plan(root, p)
        r = tc("validate", root, ok=False)
        assert word in (r.stdout + r.stderr).lower(), (r.stdout + r.stderr)

    bad(lambda p: p["shots"][ramp_i]["speed"][0].update(speed=6.0), "speed")
    bad(lambda p: p["shots"][ramp_i]["speed"][0].update(speed=0.1), "speed")
    def push_out(p):
        e = p["shots"][fx_i]["effects"][0]
        e["at"] = p["shots"][fx_i]["end"] - 0.01
        e["duration"] = 0.5
    bad(push_out, "effect")
    def starve(p):
        s = p["shots"][ramp_i]
        for k in s["speed"]:
            k["speed"] = 4.0
        s["in"] = 9.5   # footage clips are 10 s long; 4x over the shot needs far more than 0.5 s
        s["out"] = 10.0
    bad(starve, "source")
    save_plan(root, plan)
    tc("validate", root)
