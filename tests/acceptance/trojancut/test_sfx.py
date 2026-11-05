"""D10: AB17 (built-in pack, user sfx classification, placement and mix)."""
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from _helpers import (REPO, SKILL, engine_env, load, make_clip, make_ref, make_song, outside_band_energy,
                      read_audio, read_audio_peak, rms_db, run_pipeline, seg, tc, write_brief, write_wav)

MAKE = SKILL / "scripts" / "make_sfx.py"
TYPES = ["whoosh", "swoosh", "riser", "impact", "subdrop", "hit", "glitch", "pop", "shutter"]


def digest(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).iterdir())}


# ---------------------------------------------------------------- (a) built-in pack

def test_pack_regenerates_identically(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        subprocess.run([sys.executable, str(MAKE), "--out", str(d)], check=True, capture_output=True)
    assert digest(a) == digest(b)
    shipped = SKILL / "sfx"
    assert digest(a) == digest(shipped), "shipped pack differs from the script's output"


def test_pack_contents_and_manifest():
    pack = SKILL / "sfx"
    wavs = sorted(pack.glob("*.wav"))
    total = sum(p.stat().st_size for p in pack.iterdir())
    assert total < 3 * 1024 * 1024, total
    man = json.loads((pack / "manifest.json").read_text())
    entries = man["sounds"] if isinstance(man, dict) else man
    assert {e["name"] for e in entries} == {p.name for p in wavs}
    by_type = {}
    for e in entries:
        for k in ("name", "type", "duration", "peak", "loudness", "tags"):
            assert k in e, (k, e)
        by_type.setdefault(e["type"], []).append(e)
        x = read_audio(pack / e["name"], sr=44100)
        assert abs(len(x) / 44100 - e["duration"]) < 0.02
        assert 0 < e["duration"] <= 4.0
        peak = float(np.max(np.abs(x)))
        assert abs(20 * math.log10(peak) - e["peak"]) < 0.6, (e["name"], peak, e["peak"])
        assert -2.0 <= e["peak"] <= 0.0
    for t in TYPES:
        assert 2 <= len(by_type.get(t, [])) <= 4, (t, len(by_type.get(t, [])))
    # variants of a type differ
    for t in TYPES:
        names = [e["name"] for e in by_type[t]]
        hashes = {hashlib.sha256((pack / n).read_bytes()).hexdigest() for n in names}
        assert len(hashes) == len(names)


def test_pack_sound_shapes():
    pack = SKILL / "sfx"
    man = json.loads((pack / "manifest.json").read_text())
    entries = man["sounds"] if isinstance(man, dict) else man
    first = {}
    for e in entries:
        first.setdefault(e["type"], e["name"])

    def env(name, n=20):
        x = read_audio(pack / name, sr=22050)
        parts = np.array_split(np.abs(x), n)
        return np.array([p.mean() for p in parts])

    riser = env(first["riser"])
    assert riser[-5:].mean() > 3 * riser[:5].mean(), "riser does not rise"
    impact = env(first["impact"])
    assert np.argmax(impact) <= 2 and impact[0:3].max() > 4 * impact[-5:].mean(), "impact has no sharp attack"


# ---------------------------------------------------------------- (b) user files

def shaped(kind, sr=44100, dur=1.0):
    t = np.arange(int(sr * dur)) / sr
    rng = np.random.default_rng(7)
    if kind == "sharp":
        return np.sin(2 * np.pi * 180 * t) * np.exp(-t * 18) * np.minimum(1, t / 0.002)
    if kind == "rising":
        return np.sin(2 * np.pi * (200 + 600 * t) * t) * (t / dur) ** 2
    if kind == "sweep":
        n = rng.normal(0, 1, len(t))
        spec = np.fft.rfft(n)
        f = np.fft.rfftfreq(len(n), 1 / sr)
        out = np.zeros(len(t))
        for k in range(10):  # band-pass noise whose centre sweeps up then down, bell envelope
            c = 500 + 3000 * math.sin(math.pi * (k + 0.5) / 10)
            band = np.fft.irfft(spec * np.exp(-((f - c) / 600) ** 2), len(n))
            w = np.zeros(len(t))
            a, b = k * len(t) // 10, (k + 1) * len(t) // 10
            w[a:b] = 1
            out += band * w
        return out * np.sin(np.pi * t / dur)
    if kind == "flat":
        return 0.5 * np.sin(2 * np.pi * 440 * t)
    raise ValueError(kind)


@pytest.fixture(scope="module")
def user_sfx(tmp_path_factory):
    proj = tmp_path_factory.mktemp("usfx") / "p"
    make_clip(proj / "footage" / "a.mp4", "203060", w=320, h=180, dur=5, moving=False)
    files = {
        "Whoosh_Big.wav": "flat", "impact-01.wav": "flat", "my riser.wav": "flat", "boom2.wav": "flat",
        "glitchy.wav": "flat", "clickclack.wav": "flat",
        "thing1.wav": "sharp", "thing2.wav": "rising", "thing3.wav": "sweep", "thing4.wav": "flat",
    }
    for name, kind in files.items():
        x = shaped(kind)
        write_wav(proj / "sfx" / name, 0.8 * x / np.max(np.abs(x)))
    write_brief(proj, music="none", logo="", sfx_source="mine", sfx_amount="some")
    tc("ingest", proj)
    idx = load(proj, "index.json")
    return {Path(e["path"]).name: e for e in idx["sfx"]}, idx


def test_classified_by_name(user_sfx):
    sfx, idx = user_sfx
    assert sfx["Whoosh_Big.wav"]["type"] == "whoosh" and sfx["Whoosh_Big.wav"]["type_from"] == "name"
    assert sfx["impact-01.wav"]["type"] == "impact"
    assert sfx["my riser.wav"]["type"] == "riser"
    assert sfx["boom2.wav"]["type"] == "boom"
    assert sfx["glitchy.wav"]["type"] == "glitch"
    assert sfx["clickclack.wav"]["type"] == "click"


def test_classified_by_shape(user_sfx):
    sfx, idx = user_sfx
    assert sfx["thing1.wav"]["type"] == "hit" and sfx["thing1.wav"]["type_from"] == "shape"
    assert sfx["thing2.wav"]["type"] == "riser"
    assert sfx["thing3.wav"]["type"] == "whoosh"
    assert sfx["thing4.wav"]["type"] == "other"


def test_sfx_index_is_text_only(user_sfx):
    sfx, idx = user_sfx
    for e in sfx.values():
        assert abs(e["duration"] - 1.0) < 0.05 and e["loudness_db"] < 0
    assert not any("sfx" in p for p in idx["claude_images"])


# ---------------------------------------------------------------- (c) placement + mix

def project(root, amount, source="built-in", intensity="medium", music=True, user=None, n=6):
    root = Path(root)
    colours = ["1e3a6e", "6aa0d0", "1a4a2a", "70b8a0", "2a2a50", "8090d0"]
    for i in range(n):
        make_clip(root / "footage" / f"c{i}.mp4", colours[i % 6], w=320, h=180, dur=8, moving=False)
    make_ref(root / "refs" / "r.mp4", ["f0a040", "5a1808"], 1.2, w=320, h=180, n_shots=8, moving=False)
    if music:
        # soft pad with no beat clicks, so effect onsets are measurable
        t = np.arange(44100 * 40) / 44100
        write_wav(root / "music" / "pad.wav", 0.25 * np.sin(2 * np.pi * 220 * t))
    for name, x in (user or {}).items():
        write_wav(root / "sfx" / name, x)
    write_brief(root, aspect="16:9", resolution=180, fps=25, music="music/pad.wav" if music else "none",
                logo="", title_text="POW", effects_intensity=intensity, sfx_amount=amount, sfx_source=source,
                min_seconds=14, max_seconds=18)
    run_pipeline(root, env=engine_env("ffmpeg"))
    return load(root, "plan.json"), load(root, "report.json")


@pytest.fixture(scope="module")
def some(tmp_path_factory):
    root = tmp_path_factory.mktemp("some") / "p"
    return root, *project(root, "some")


@pytest.fixture(scope="module")
def lots(tmp_path_factory):
    root = tmp_path_factory.mktemp("lots") / "p"
    return root, *project(root, "lots")


def test_counts_per_amount(some, lots):
    for (root, plan, report), per in ((some, 4), (lots, 2)):
        cuts = len(plan["shots"]) - 1
        n = len(plan["sfx"])
        assert n >= 1
        assert abs(n - cuts / per) <= max(2, 0.35 * cuts / per), (n, cuts, per)
    assert len(lots[1]["sfx"]) > len(some[1]["sfx"])


def test_placement_rules(lots):
    root, plan, report = lots
    title = plan["title"]
    types_at = [(e["at"], e["type"]) for e in plan["sfx"]]
    assert any(abs(at - title["start"]) <= 0.6 and t in ("impact", "hit") for at, t in types_at), types_at
    soft = [s["start"] for s in plan["shots"][1:] if s["transition"]["type"] != "cut"]
    for t in soft:
        near = [ty for at, ty in types_at if abs(at - t) <= 0.6]
        if near:
            assert any(ty in ("whoosh", "swoosh") for ty in near), (t, near)
    ev = sorted((e["start"], e["start"] + e["duration"]) for e in plan["sfx"])
    for (a0, a1), (b0, b1) in zip(ev, ev[1:]):
        assert b0 >= a1 - 1e-3, f"overlapping effects {a0}-{a1} and {b0}-{b1}"
    for e in plan["sfx"]:
        assert (root / e["file"]).exists() or Path(e["file"]).is_absolute() and Path(e["file"]).exists()
        assert e["gain_db"] <= -4


def test_effects_audible_at_planned_times(lots):
    """The pad is a pure 220 Hz sine, so broadband energy outside 150-300 Hz marks an effect."""
    root, plan, report = lots
    x = read_audio(root / "out" / "final.mp4")
    sr = 22050

    def power_db(a):
        return 10 * math.log10(outside_band_energy(a, 150, 300) / max(1, len(a)) + 1e-15)

    win = int(0.25 * sr)
    baseline = min(power_db(x[i:i + win]) for i in range(0, len(x) - win, win // 2))
    heard = 0
    for e in plan["sfx"]:
        assert abs(e["at"] - e["start"]) <= e["duration"] + 1e-3
        during = power_db(seg(x, e["start"], e["start"] + e["duration"]))
        heard += during > baseline + 10
    assert plan["sfx"] and heard >= 0.8 * len(plan["sfx"]), f"{heard}/{len(plan['sfx'])} effects audible"


def test_no_clipping_and_level(lots):
    root, plan, report = lots
    assert read_audio_peak(root / "out" / "final.mp4") <= 1.0
    x = read_audio(root / "out" / "final.mp4")
    assert np.mean(np.abs(x) > 0.999) < 1e-4


def test_none_places_nothing(tmp_path):
    root = tmp_path / "none"
    plan, report = project(root, "none")
    assert plan["sfx"] == []
    assert report["sfx_count"] == 0


def test_both_prefers_user_file(tmp_path):
    root = tmp_path / "both"
    t = np.arange(22050) / 44100
    mine = 0.7 * np.sin(2 * np.pi * 150 * t) * np.exp(-t * 20) * np.minimum(1, t / 0.002)
    plan, report = project(root, "lots", source="both", user={"impact_mine.wav": mine})
    impacts = [e for e in plan["sfx"] if e["type"] in ("impact", "hit")]
    assert impacts and all(Path(e["file"]).name == "impact_mine.wav" for e in impacts if e["type"] == "impact")
    others = [e for e in plan["sfx"] if e["type"] not in ("impact",)]
    assert all("impact_mine" not in e["file"] for e in others)


def test_validate_checks_effect_files(some):
    root, plan, report = some
    bad = json.loads(json.dumps(plan))
    bad["sfx"].append({"file": "sfx/not_there.wav", "type": "pop", "start": 1.0, "at": 1.0, "duration": 0.2,
                       "gain_db": -6, "reason": "test"})
    (root / "work" / "plan.json").write_text(json.dumps(bad))
    r = tc("validate", root, ok=False)
    assert "sfx" in (r.stdout + r.stderr).lower() and "not_there.wav" in (r.stdout + r.stderr)
    (root / "work" / "plan.json").write_text(json.dumps(plan))
    tc("validate", root)
