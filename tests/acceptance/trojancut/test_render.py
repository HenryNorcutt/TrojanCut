"""D4: AB7 (HyperFrames render), AB8 (ffmpeg render / fallback), AB9 (check)."""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from _helpers import (basic_project, dominant_freq, engine_env, ff, frame, has_audio, load, magenta_mask,
                      path_without_node, probe, read_audio, run_pipeline, seg, tc, vstream, write_brief)

W, H = 160, 90


@pytest.fixture(scope="module", autouse=True)
def setup_done():
    tc("setup")


def build(proj, engine, **brief):
    defaults = dict(n_clips=4, static=True, aspect="16:9", resolution=360, fps=25, min_seconds=6, max_seconds=9,
                    title_text="HELLO WORLD", effects_intensity="low", bpm=96, ref_shot=1.25)
    defaults.update(brief)
    basic_project(proj, **defaults)
    run_pipeline(proj, env=engine_env(engine))
    return load(proj, "plan.json"), load(proj, "report.json")


def safe_times(plan, t0, t1, n):
    """n times in [t0, t1] at least 0.3 s away from every shot boundary."""
    bounds = [s["start"] for s in plan["shots"]]
    cand = np.linspace(t0, t1, 60)
    ok = [t for t in cand if min(abs(t - b) for b in bounds) > 0.3]
    assert len(ok) >= n, (t0, t1, bounds)
    return [ok[int(i * (len(ok) - 1) / max(1, n - 1))] for i in range(n)]


def text_mask(img):
    """Pixels far from the frame's median colour in the central band (title area), logo corner excluded."""
    h, w, _ = img.shape
    med = np.median(img.reshape(-1, 3), axis=0)
    far = np.abs(img - med).sum(axis=2) > 90
    far[:, int(w * 0.75):][: int(h * 0.35)] = False
    band = np.zeros_like(far)
    band[int(h * 0.2): int(h * 0.8), int(w * 0.05): int(w * 0.95)] = True
    return far & band


def common_output_checks(proj, plan, fps=25, size=(640, 360)):
    final = proj / "out" / "final.mp4"
    v = vstream(final)
    assert (v["width"], v["height"]) == size
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    num, den = map(int, v["r_frame_rate"].split("/"))
    assert abs(num / den - fps) < 0.01
    assert has_audio(final)
    dur = float(probe(final)["format"]["duration"])
    assert abs(dur - plan["duration"]) < 0.3
    # music track is the song (440 Hz) not silence
    x = read_audio(final)
    assert dominant_freq(seg(x, 1, dur - 1)) == pytest.approx(440, abs=15)
    # logo in its corner through the edit
    frames = [frame(final, t, W, H) for t in np.linspace(0.3, dur - 0.3, 8)]
    corner = [magenta_mask(f[: H // 3, W * 2 // 3:]).sum() for f in frames]
    assert sum(c >= 20 for c in corner) >= 7, corner
    # grade: cool footage pushed warm
    rb = np.mean([(f[..., 0] - f[..., 2])[~magenta_mask(f)].mean() for f in frames])
    assert rb > -20, rb  # source footage is strongly blue (R-B ~ -80)
    return final, dur


@pytest.fixture(scope="module")
def hf(tmp_path_factory):
    proj = tmp_path_factory.mktemp("hf") / "p"
    plan, report = build(proj, "auto")
    return proj, plan, report


@pytest.fixture(scope="module")
def ffm(tmp_path_factory):
    proj = tmp_path_factory.mktemp("ff") / "p"
    plan, report = build(proj, "ffmpeg")
    return proj, plan, report


def test_hyperframes_output(hf):
    proj, plan, report = hf
    assert report["ok"] is True, report
    assert report["engine"] == "hyperframes"
    assert report["layers"]["title"] == "hyperframes" and report["layers"]["logo"] == "hyperframes"
    common_output_checks(proj, plan)


def test_hyperframes_title_is_animated(hf):
    proj, plan, report = hf
    final = proj / "out" / "final.mp4"
    t = plan["title"]
    ts = safe_times(plan, t["start"] + 0.05, t["end"] - 0.05, 4)
    masks = [text_mask(frame(final, x, W, H)) for x in ts]
    assert max(m.sum() for m in masks) >= 40, [m.sum() for m in masks]
    diffs = [int((a ^ b).sum()) for a, b in zip(masks, masks[1:])]
    assert max(diffs) >= 25, f"title does not move: {diffs}"
    after = [x for x in np.linspace(t["end"] + 0.4, plan["duration"] - 0.3, 6)]
    assert all(text_mask(frame(final, x, W, H)).sum() < 15 for x in after)


def test_ffmpeg_output_static_title(ffm):
    proj, plan, report = ffm
    assert report["ok"] is True, report
    assert report["engine"] == "ffmpeg"
    assert report["layers"]["title"] == "ffmpeg"
    final, dur = common_output_checks(proj, plan)
    t = plan["title"]
    ts = safe_times(plan, t["start"] + 0.05, t["end"] - 0.05, 3)
    masks = [text_mask(frame(final, x, W, H)) for x in ts]
    assert min(m.sum() for m in masks) >= 40, [m.sum() for m in masks]
    diffs = [int((a ^ b).sum()) for a, b in zip(masks, masks[1:])]
    assert max(diffs) <= 12, f"ffmpeg title should be static: {diffs}"


def test_transitions_rendered(tmp_path):
    proj = tmp_path / "tr"
    plan, report = build(proj, "ffmpeg", effects_intensity="high", n_clips=5, title_text="",
                         clip_colours=["1020c0", "c0c020", "20c040", "c02080", "20a0c0"])
    final = proj / "out" / "final.mp4"
    soft = [s for s in plan["shots"][1:] if s["transition"]["type"] != "cut"]
    assert soft, "high intensity produced no transitions"
    blended = 0
    for s in soft:
        d = s["transition"]["duration"]
        mid = frame(final, s["start"], W, H).reshape(-1, 3).mean(0)
        a = frame(final, s["start"] - d / 2 - 0.15, W, H).reshape(-1, 3).mean(0)
        b = frame(final, s["start"] + d / 2 + 0.15, W, H).reshape(-1, 3).mean(0)
        if np.abs(mid - a).sum() > 12 and np.abs(mid - b).sum() > 12:
            blended += 1
    assert blended >= 0.6 * len(soft), (blended, len(soft))


def test_auto_without_node_falls_back(tmp_path):
    proj = tmp_path / "nn"
    basic_project(proj, n_clips=3, static=True, min_seconds=6, max_seconds=9)
    env = engine_env("auto", PATH=path_without_node(tmp_path))
    run_pipeline(proj, env=env)
    report = load(proj, "report.json")
    assert report["engine"] == "ffmpeg" and report["fallback_reason"]
    assert report["ok"] is True


def test_auto_without_browser_falls_back(tmp_path):
    proj = tmp_path / "nb"
    basic_project(proj, n_clips=3, static=True, min_seconds=6, max_seconds=9)
    env = engine_env("auto", TROJANCUT_BROWSER=tmp_path / "missing-chrome")
    run_pipeline(proj, env=env)
    report = load(proj, "report.json")
    assert report["engine"] == "ffmpeg"
    assert "browser" in report["fallback_reason"].lower() or "chrome" in report["fallback_reason"].lower()


def test_vertical_30fps(tmp_path):
    proj = tmp_path / "v"
    plan, report = build(proj, "ffmpeg", aspect="9:16", resolution=270, fps=30)
    v = vstream(proj / "out" / "final.mp4")
    assert (v["width"], v["height"]) == (270, 480)
    num, den = map(int, v["r_frame_rate"].split("/"))
    assert abs(num / den - 30) < 0.01


# ---------------------------------------------------------------- AB9

@pytest.fixture()
def checked(tmp_path):
    proj = tmp_path / "ck"
    plan, report = build(proj, "ffmpeg", n_clips=3, title_text="")
    assert report["ok"] is True
    for k in ("duration", "aspect", "audio", "black"):
        assert k in report["checks"], report
    return proj


def expect_bad(proj, word):
    r = tc("check", proj, ok=False)
    rep = load(proj, "report.json")
    assert rep["ok"] is False
    assert any(word in reason.lower() for reason in rep["reasons"]), rep["reasons"]


def test_check_duration(checked):
    b = yaml.safe_load((checked / "brief.yaml").read_text())
    b["min_seconds"], b["max_seconds"] = 30, 40
    (checked / "brief.yaml").write_text(yaml.safe_dump(b))
    expect_bad(checked, "duration")


def test_check_aspect(checked):
    final = checked / "out" / "final.mp4"
    ff("-i", final, "-vf", "scale=360:360,setsar=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
       checked / "sq.mp4")
    (checked / "sq.mp4").replace(final)
    expect_bad(checked, "aspect")


def test_check_audio(checked):
    final = checked / "out" / "final.mp4"
    ff("-i", final, "-an", "-c:v", "copy", checked / "na.mp4")
    (checked / "na.mp4").replace(final)
    expect_bad(checked, "audio")


def test_check_black(checked):
    final = checked / "out" / "final.mp4"
    ff("-i", final, "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,1,2.6)'",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", checked / "bk.mp4")
    (checked / "bk.mp4").replace(final)
    expect_bad(checked, "black")
