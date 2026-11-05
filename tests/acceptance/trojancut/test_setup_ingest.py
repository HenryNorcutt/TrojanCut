"""D1: AB1 (setup) and AB2 (ingest)."""
import json
import re
import time
import zipfile
from pathlib import Path

import pytest

from _helpers import (REPO, engine_env, image_size, make_clip, make_logo, make_ref, make_song, path_without_node,
                      probe, tc, write_brief)


def engine_line(out):
    m = re.search(r"engine:\s*(hyperframes|ffmpeg)", out)
    assert m, f"setup must print 'engine: <name>'\n{out[-2000:]}"
    return m.group(1)


def tree_state(root):
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in Path(root).rglob("*") if p.is_file()}


# ---------------------------------------------------------------- AB1

def test_setup_installs_once_then_is_fast(tmp_path):
    home = tmp_path / "tchome"
    env = engine_env("auto", TROJANCUT_HOME=home)
    r1 = tc("setup", env=env)
    assert engine_line(r1.stdout + r1.stderr) == "hyperframes", r1.stdout[-2000:]
    pkgs = list(home.rglob("node_modules/hyperframes/package.json"))
    assert pkgs, "hyperframes not installed under TROJANCUT_HOME"
    assert json.loads(pkgs[0].read_text())["version"] == "0.9.16"
    before = {k: v for k, v in tree_state(home).items() if "node_modules" in k}
    t0 = time.time()
    r2 = tc("setup", env=env)
    assert time.time() - t0 < 10, f"second setup took {time.time() - t0:.1f}s"
    assert engine_line(r2.stdout + r2.stderr) == "hyperframes"
    after = {k: v for k, v in tree_state(home).items() if "node_modules" in k}
    assert before == after, "second setup reinstalled node packages"


def test_setup_without_node_reports_ffmpeg(tmp_path):
    env = engine_env("auto", TROJANCUT_HOME=tmp_path / "h", PATH=path_without_node(tmp_path))
    r = tc("setup", env=env)
    assert engine_line(r.stdout + r.stderr) == "ffmpeg"


def test_setup_without_browser_reports_ffmpeg(tmp_path):
    # An explicit browser override that does not exist means "no usable browser here".
    env = engine_env("auto", TROJANCUT_HOME=tmp_path / "h", TROJANCUT_BROWSER=tmp_path / "no-such-chrome",
                     HYPERFRAMES_BROWSER_PATH=tmp_path / "no-such-chrome")
    r = tc("setup", env=env)
    assert engine_line(r.stdout + r.stderr) == "ffmpeg"


def test_requirements_pinned():
    req = (REPO / "skills" / "trojancut" / "scripts" / "requirements.txt").read_text().split()
    names = {line.split("==")[0].lower() for line in req if line.strip()}
    assert {"numpy", "pillow", "pyyaml"} <= names
    assert all("==" in line for line in req if line.strip() and not line.startswith("#"))
    pkg = json.loads((REPO / "skills" / "trojancut" / "engine" / "package.json").read_text())
    assert pkg["dependencies"]["hyperframes"] == "0.9.16"
    assert (REPO / "skills" / "trojancut" / "engine" / "package-lock.json").exists()


# ---------------------------------------------------------------- AB2

@pytest.fixture(scope="module")
def ingested(tmp_path_factory):
    proj = tmp_path_factory.mktemp("ing") / "p"
    make_clip(proj / "footage" / "wide.mp4", "203060", w=640, h=360, fps=25, dur=5, noise=True)
    make_clip(proj / "footage" / "still_cam.mp4", "406080", w=480, h=480, fps=30, dur=4, moving=False)
    make_clip(proj / "footage" / "tall.mp4", "305070", w=360, h=640, fps=24, dur=7)
    z = proj / "footage" / "batch.zip"
    tmp = proj / "ztmp"
    make_clip(tmp / "zipped_a.mp4", "102040", dur=3)
    make_clip(tmp / "zipped_b.mp4", "204010", dur=3)
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(tmp / "zipped_a.mp4", "zipped_a.mp4")
        zf.write(tmp / "zipped_b.mp4", "sub/zipped_b.mp4")
    make_logo(tmp / "badge.png", size=300, rgb=(0, 255, 0))
    (proj / "assets").mkdir(parents=True)
    with zipfile.ZipFile(proj / "assets" / "imgs.zip", "w") as zf:
        zf.write(tmp / "badge.png", "badge.png")
    make_logo(proj / "assets" / "logo.png")
    make_ref(tmp / "zref.mp4", ["f0a040", "300c04"], 1.0, n_shots=4)
    (proj / "refs").mkdir()
    with zipfile.ZipFile(proj / "refs" / "refs.zip", "w") as zf:
        zf.write(tmp / "zref.mp4", "zref.mp4")
    make_song(tmp / "tune.wav", 100, 10, 330)
    (proj / "music").mkdir()
    with zipfile.ZipFile(proj / "music" / "songs.zip", "w") as zf:
        zf.write(tmp / "tune.wav", "tune.wav")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    write_brief(proj, music="music/tune.wav")
    tc("ingest", proj)
    return proj, json.loads((proj / "work" / "index.json").read_text())


def by_name(entries, name):
    hits = [e for e in entries if Path(e["path"]).name == name]
    assert hits, f"{name} not indexed: {[e['path'] for e in entries]}"
    return hits[0]


def test_ingest_extracts_every_zip(ingested):
    proj, idx = ingested
    names = {Path(c["path"]).name for c in idx["clips"]}
    assert names == {"wide.mp4", "still_cam.mp4", "tall.mp4", "zipped_a.mp4", "zipped_b.mp4"}, names
    assert any(Path(i["path"]).name == "badge.png" for i in idx["images"])
    assert any(Path(r["path"]).name == "zref.mp4" for r in idx["refs"])
    assert any(Path(m["path"]).name == "tune.wav" for m in idx["music"])
    for group in ("clips", "images", "refs", "music"):
        for e in idx[group]:
            assert (proj / e["path"]).exists(), e["path"]


def test_ingest_indexes_clip_facts(ingested):
    proj, idx = ingested
    wide = by_name(idx["clips"], "wide.mp4")
    assert abs(wide["duration"] - 5) < 0.2 and (wide["width"], wide["height"]) == (640, 360)
    assert abs(wide["fps"] - 25) < 0.1 and wide["has_audio"] is True
    tall = by_name(idx["clips"], "tall.mp4")
    assert (tall["width"], tall["height"]) == (360, 640) and abs(tall["fps"] - 24) < 0.1
    assert tall["has_audio"] is False
    still = by_name(idx["clips"], "still_cam.mp4")
    assert abs(still["fps"] - 30) < 0.1
    assert still["motion"] < tall["motion"], (still["motion"], tall["motion"])
    logo = by_name(idx["images"], "logo.png")
    assert (logo["width"], logo["height"]) == (256, 256)


def test_ingest_contact_sheets(ingested):
    proj, idx = ingested
    imgs = idx["claude_images"]
    assert len(imgs) == len(idx["clips"]), "one contact sheet per clip"
    for c in idx["clips"]:
        assert c["sheet"] in imgs
        assert 1 <= c["sheet_tiles"] <= 16
    for rel in imgs:
        assert not Path(rel).is_absolute()
        w, h = image_size(proj / rel)
        assert max(w, h) <= 1024, (rel, w, h)


def test_ingest_rerun_is_stable(ingested):
    proj, idx = ingested
    tc("ingest", proj)
    again = json.loads((proj / "work" / "index.json").read_text())
    assert len(again["clips"]) == len(idx["clips"])


def test_ingest_missing_project_fails_cleanly(tmp_path):
    r = tc("ingest", tmp_path / "nope", ok=False)
    assert "nope" in r.stdout + r.stderr
