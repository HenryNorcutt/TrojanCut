"""End-to-end check for TrojanCut. Written by the coordinator; protected. The build must not edit it.

Runs the full CLI pipeline on synthetic fixtures (make_fixtures.py) once per render engine and
measures the output independently with ffmpeg/ffprobe. Standard library + pytest only.
"""
import json
import os
import statistics
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TC = REPO / "skills" / "trojancut" / "scripts" / "tc.py"
W, H = 270, 480          # analysis size for 9:16 output
MAX_PIPELINE_SECONDS = 20 * 60


def run(*args, env=None, timeout=MAX_PIPELINE_SECONDS):
    r = subprocess.run([sys.executable, str(TC), *map(str, args)], capture_output=True, text=True,
                       env=env, timeout=timeout)
    assert r.returncode == 0, f"tc.py {' '.join(map(str, args))} exited {r.returncode}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
    return r


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def frames_rgb(path, n, w, h):
    dur = float(probe(path)["format"].get("duration", 0))
    out = []
    for k in range(n):
        t = dur * (k + 0.5) / n
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                              "-vf", f"scale={w}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        assert len(raw) == w * h * 3
        out.append(raw)
    return out


def is_magenta(r, g, b):
    return r > 190 and g < 90 and b > 190


def cut_times(path):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf",
                        f"scale={W}:{H},select='gt(scene,0.15)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(line.split("pts_time:")[1].split()[0]) for line in r.stderr.splitlines() if "pts_time:" in line]


@pytest.fixture(scope="module")
def setup_done():
    run("setup", timeout=30 * 60)


@pytest.mark.parametrize("engine", ["auto", "ffmpeg"])
def test_pipeline(tmp_path, engine, setup_done):
    proj = tmp_path / "proj"
    subprocess.run([sys.executable, str(REPO / "tests" / "e2e" / "make_fixtures.py"), str(proj)], check=True)
    env = dict(os.environ, TROJANCUT_ENGINE=engine)

    t0 = time.time()
    for cmd in ("ingest", "analyze-refs", "autoplan", "render", "check"):
        run(cmd, proj, env=env)
    elapsed = time.time() - t0
    assert elapsed < MAX_PIPELINE_SECONDS, f"pipeline took {elapsed:.0f}s"

    # Footage index: zip extracted, every clip indexed.
    index = json.loads((proj / "work" / "index.json").read_text())
    assert len(index["clips"]) == 6, f"expected 6 clips (4 loose + 2 in zip), got {len(index['clips'])}"

    # Reference analysis: cut rhythm and tempo measured, not assumed.
    style = json.loads((proj / "work" / "style.json").read_text())
    assert 0.8 <= style["median_shot_seconds"] <= 1.25, style["median_shot_seconds"]
    bpm = style["bpm"]
    assert any(abs(bpm - b) <= 3 for b in (60, 120, 240)), bpm

    # Token budget: what Claude is asked to look at stays small.
    imgs = index["claude_images"] + style["claude_images"]
    assert 0 < len(imgs) <= 40, f"{len(imgs)} images for Claude"
    for rel in imgs:
        s = next(st for st in probe(proj / rel)["streams"] if st["codec_type"] == "video")
        assert max(s["width"], s["height"]) <= 1024, rel
    text_bytes = (proj / "work" / "index.json").stat().st_size + (proj / "work" / "style.json").stat().st_size
    assert text_bytes <= 60_000, f"index+style JSON is {text_bytes} bytes"

    # Output file: format, length, audio.
    final = proj / "out" / "final.mp4"
    info = probe(final)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert any(s["codec_type"] == "audio" for s in info["streams"]), "no audio track"
    dur = float(info["format"]["duration"])
    assert 15 - 0.5 <= dur <= 30 + 0.5, dur

    report = json.loads((proj / "out" / "report.json").read_text())
    assert report["ok"] is True

    # Cut rhythm follows the reference and lands on the music's beat grid (0.5 s).
    cuts = cut_times(final)
    assert len(cuts) >= dur / 3, f"only {len(cuts)} hard cuts in {dur:.1f}s"
    gaps = [b - a for a, b in zip([0.0] + cuts, cuts + [dur])]
    assert 0.5 <= statistics.median(gaps) <= 2.5, statistics.median(gaps)
    best = 0.0
    for k in range(25):
        phase = k * 0.02
        near = sum(1 for c in cuts if min((c - phase) % 0.5, 0.5 - (c - phase) % 0.5) <= 0.1)
        best = max(best, near / len(cuts))
    assert best >= 0.6, f"only {best:.0%} of cuts on the beat grid"

    # Logo visible through the edit.
    out_frames = frames_rgb(final, 10, W, H)
    with_logo = 0
    rb_out = []
    for raw in out_frames:
        px = list(struct.iter_unpack("BBB", raw))
        if sum(1 for p in px if is_magenta(*p)) >= 150:
            with_logo += 1
        rb_out += [p[0] - p[2] for p in px if not is_magenta(*p)]
    assert with_logo >= 8, f"logo found in {with_logo}/10 frames"

    # Colour moved toward the warm reference, away from the cool source footage.
    rb_src = []
    for clip in sorted((proj / "footage").rglob("*.mp4"))[:3]:
        for raw in frames_rgb(clip, 2, 480, 270):
            rb_src += [p[0] - p[2] for p in struct.iter_unpack("BBB", raw)]
    assert statistics.mean(rb_out) > statistics.mean(rb_src) + 20, (statistics.mean(rb_out), statistics.mean(rb_src))


def test_package(tmp_path):
    run("package", "--out", tmp_path)
    z = tmp_path / "trojancut.zip"
    assert z.exists()
    assert z.stat().st_size <= 15 * 1024 * 1024
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert "trojancut/SKILL.md" in names
        assert "trojancut/scripts/tc.py" in names
        assert not any("node_modules" in n or n.endswith(".pyc") for n in names)
        skill = zf.read("trojancut/SKILL.md").decode()
    assert skill.startswith("---\n")
    front = skill.split("---\n")[1]
    fields = dict(line.split(":", 1) for line in front.strip().splitlines() if ":" in line)
    assert fields["name"].strip() == "trojancut"
    desc = fields["description"].strip()
    assert 0 < len(desc) <= 1024 and "<" not in desc and ">" not in desc
    # claude.ai rejects skill uploads whose frontmatter has any other key ("Unexpected key(s)").
    allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    for zname, skill in (("trojancut.zip", "trojancut"), ("templatetrojancut.zip", "templatetrojancut")):
        with zipfile.ZipFile(tmp_path / zname) as zf:
            md = zf.read(f"{skill}/SKILL.md").decode()
            # claude.ai also rejects skill uploads that contain a nested zip
            assert not [n for n in zf.namelist() if n.lower().endswith(".zip")], zname
        keys = {l.split(":", 1)[0].strip() for l in md.split("---\n")[1].splitlines()
                if ":" in l and not l.startswith((" ", "\t"))}
        assert "name" in keys and keys <= allowed, (zname, keys)
