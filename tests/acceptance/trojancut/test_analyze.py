"""D2: AB3 (reference analysis) and AB4 (Claude image/text budget)."""
import json
from pathlib import Path

import numpy as np
import pytest

from _helpers import (basic_project, image_size, make_clip, make_ref, make_song, tc, write_brief)


def analyze(proj):
    tc("ingest", proj)
    tc("analyze-refs", proj)
    return json.loads((Path(proj) / "work" / "style.json").read_text())


def octave_ok(bpm, true_bpm, tol=3):
    return any(abs(bpm - true_bpm * m) <= tol * m for m in (0.5, 1, 2))


def ref_entry(style, name):
    return next(r for r in style["refs"] if Path(r["path"]).name == name)


@pytest.fixture(scope="module")
def two_refs(tmp_path_factory):
    """Ref A: 0.8 s shots, 150 BPM own audio. Ref B: silent, 1.5 s shots -> beats from brief music (96 BPM)."""
    proj = tmp_path_factory.mktemp("an") / "p"
    make_clip(proj / "footage" / "a.mp4", "203060", dur=5)
    make_clip(proj / "footage" / "b.mp4", "305070", dur=5)
    wav = proj / ".a.wav"
    make_song(wav, 150, 12, 520)
    make_ref(proj / "refs" / "fast.mp4", ["e0a020", "401008", "c05010"], 0.8, w=640, h=360, n_shots=12, audio=wav)
    wav.unlink()
    make_ref(proj / "refs" / "slow.mp4", ["20c0a0", "082010"], 1.5, w=400, h=400, n_shots=8)
    make_song(proj / "music" / "bed.wav", 96, 40, 300)
    write_brief(proj, music="music/bed.wav", aspect="1:1")
    return proj, analyze(proj)


def test_cut_times_and_shot_length(two_refs):
    proj, style = two_refs
    fast = ref_entry(style, "fast.mp4")
    slow = ref_entry(style, "slow.mp4")
    assert abs(fast["median_shot_seconds"] - 0.8) <= 0.12, fast["median_shot_seconds"]
    assert abs(slow["median_shot_seconds"] - 1.5) <= 0.15, slow["median_shot_seconds"]
    expect = [0.8 * k for k in range(1, 12)]
    found = fast["cuts"]
    hit = sum(1 for e in expect if min(abs(e - c) for c in found) <= 0.1)
    assert hit >= 10, (found, expect)
    assert len(found) <= 13


def test_tempo_from_own_audio_and_from_brief_music(two_refs):
    proj, style = two_refs
    fast = ref_entry(style, "fast.mp4")
    slow = ref_entry(style, "slow.mp4")
    assert octave_ok(fast["bpm"], 150), fast["bpm"]
    assert fast["beat_source"] == "reference"
    assert octave_ok(slow["bpm"], 96), slow["bpm"]
    assert slow["beat_source"] == "music"
    beats = np.array(fast["beats"])
    period = 60 / fast["bpm"]
    assert len(beats) >= 10
    assert np.median(np.diff(beats)) == pytest.approx(period, rel=0.05)
    # beats sit on the clicks (onsets every 0.4 s from t=0)
    err = [min(abs(b - 0.4 * round(b / 0.4)), 0.4) for b in beats]
    assert np.median(err) <= 0.05, err[:10]


def test_colour_stats_and_lut(two_refs):
    proj, style = two_refs
    fast = ref_entry(style, "fast.mp4")
    slow = ref_entry(style, "slow.mp4")
    r, g, b = fast["color"]["mean_rgb"]
    assert r > b + 40, fast["color"]
    r2, g2, b2 = slow["color"]["mean_rgb"]
    assert g2 > r2 + 20, slow["color"]
    for ref in (fast, slow):
        lut = proj / ref["lut"]
        assert lut.suffix == ".cube"
        lines = [line for line in lut.read_text().splitlines() if line.strip() and not line.startswith("#")]
        size = int(next(line.split()[1] for line in lines if line.startswith("LUT_3D_SIZE")))
        rows = [line for line in lines if line[0].isdigit() or line[0] in "-."]
        assert len(rows) == size ** 3
    # the fast (warm) LUT pushes a mid-blue input warmer
    lut = (proj / fast["lut"]).read_text().splitlines()
    size = int(next(l.split()[1] for l in lut if l.startswith("LUT_3D_SIZE")))
    rows = [list(map(float, l.split())) for l in lut if l and (l[0].isdigit() or l[0] in "-.")]
    rows = np.array(rows).reshape(size, size, size, 3)  # .cube: red fastest -> [b][g][r]
    mid = size // 2
    out = rows[int(size * 0.7), mid, int(size * 0.3)]  # input r=0.3, g=0.5, b=0.7
    assert out[0] - out[2] > 0.3 - 0.7 + 0.15, out


def test_scene_frames_deduplicated(two_refs):
    proj, style = two_refs
    imgs = style["claude_images"]
    assert imgs, "no scene frames for Claude"
    for rel in imgs:
        w, h = image_size(proj / rel)
        assert max(w, h) <= 1024
    # fast ref cycles 3 colours, slow ref 2: deduped frames should not be one per cut (12+8)
    assert len(imgs) <= 12, len(imgs)
    assert len(imgs) >= 3


def test_no_refs_fails_with_reason(tmp_path):
    proj = tmp_path / "p"
    make_clip(proj / "footage" / "a.mp4", "203060", dur=3)
    write_brief(proj, music="none")
    tc("ingest", proj)
    r = tc("analyze-refs", proj, ok=False)
    assert "ref" in (r.stdout + r.stderr).lower()


def test_budget_with_25_clips_and_many_refs(tmp_path):
    proj = tmp_path / "p"
    for i in range(25):
        make_clip(proj / "footage" / f"c{i:02d}.mp4", f"{(i * 9) % 200 + 20:02x}3060", w=320, h=180, dur=3,
                  fps=25)
    for j in range(5):
        make_ref(proj / "refs" / f"r{j}.mp4", ["f0a040", "300c04", f"{40 * j + 20:02x}8020"], 0.5,
                 w=320, h=180, n_shots=30)
    make_song(proj / "music" / "song.wav", 110, 30, 400)
    write_brief(proj, music="music/song.wav")
    style = analyze(proj)
    idx = json.loads((proj / "work" / "index.json").read_text())
    assert len(idx["clips"]) == 25
    imgs = idx["claude_images"] + style["claude_images"]
    assert 0 < len(imgs) <= 40, len(imgs)
    for rel in imgs:
        assert (proj / rel).exists()
        assert max(image_size(proj / rel)) <= 1024
    size = (proj / "work" / "index.json").stat().st_size + (proj / "work" / "style.json").stat().st_size
    assert size <= 60_000, size
    # every clip is still visible to Claude in some sheet
    covered = set()
    for c in idx["clips"]:
        assert c["sheet"] in idx["claude_images"]
        covered.add(c["path"])
    assert len(covered) == 25


def test_budget_long_reference(tmp_path):
    proj = tmp_path / "p"
    basic_project(proj, n_clips=3)
    make_ref(proj / "refs" / "long.mp4", ["f0a040", "300c04", "a0a0a0", "102030"], 0.3, w=320, h=180,
             n_shots=300)
    style = analyze(proj)
    idx = json.loads((proj / "work" / "index.json").read_text())
    assert len(idx["claude_images"] + style["claude_images"]) <= 40
    size = (proj / "work" / "index.json").stat().st_size + (proj / "work" / "style.json").stat().st_size
    assert size <= 60_000, size
    long = ref_entry(style, "long.mp4")
    assert abs(long["median_shot_seconds"] - 0.3) <= 0.08
