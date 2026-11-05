"""D3: AB5 (autoplan) and AB6 (validation errors)."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from _helpers import basic_project, load, make_clip, save_plan, tc, write_brief


def plan_for(proj):
    for s in ("ingest", "analyze-refs", "autoplan"):
        tc(s, proj)
    tc("validate", proj)
    return load(proj, "plan.json")


def cut_points(plan):
    return [s["start"] for s in plan["shots"][1:]]


@pytest.fixture(scope="module")
def p_low(tmp_path_factory):
    proj = tmp_path_factory.mktemp("pl") / "p"
    basic_project(proj, n_clips=5, ref_shot=1.25, bpm=96, min_seconds=10, max_seconds=14, effects_intensity="low")
    return proj, plan_for(proj)


def test_length_within_brief(p_low):
    proj, plan = p_low
    assert 10 <= plan["duration"] <= 14
    assert plan["shots"][0]["start"] == 0
    assert abs(plan["shots"][-1]["end"] - plan["duration"]) < 1e-3


def test_cuts_on_beat_grid_at_reference_pace(p_low):
    proj, plan = p_low
    period = 60 / 96
    beats = np.array(plan["beats"])
    assert len(beats) > 0
    assert np.median(np.diff(beats)) == pytest.approx(period, rel=0.04)
    for c in cut_points(plan):
        assert np.min(np.abs(beats - c)) <= 0.03, c
    lens = [s["end"] - s["start"] for s in plan["shots"]]
    # reference median 1.25 s; nearest beat multiple of 0.625 is 1.25
    assert 0.6 <= float(np.median(lens)) <= 2.0, lens


def test_each_clip_used_before_repeat(p_low):
    proj, plan = p_low
    used = [s["clip"] for s in plan["shots"]]
    n = len(set(load(proj, "index.json")["clips"][i]["path"] for i in range(5)))
    first = used[:n]
    assert len(set(first)) == min(n, len(used)), used


def test_shot_ranges_inside_clips(p_low):
    proj, plan = p_low
    idx = {c["path"]: c for c in load(proj, "index.json")["clips"]}
    for s in plan["shots"]:
        c = idx[s["clip"]]
        assert 0 <= s["in"] < s["out"] <= c["duration"] + 1e-3
        assert abs((s["out"] - s["in"]) - (s["end"] - s["start"])) < 0.05


def test_logo_title_grade_transitions_low(p_low):
    proj, plan = p_low
    assert plan["logo"]["file"].endswith("logo.png") and plan["logo"]["position"] == "top-right"
    assert plan["title"]["text"] == "HELLO"
    assert plan["grade"] and plan["grade"]["strength"] >= 0.9
    assert (proj / plan["grade"]["lut"]).exists()
    trans = [s["transition"]["type"] for s in plan["shots"][1:]]
    assert sum(t == "cut" for t in trans) >= 0.75 * len(trans), trans


def test_intensity_and_match_change_plan(tmp_path):
    proj = tmp_path / "hi"
    basic_project(proj, n_clips=4, ref_shot=1.25, bpm=96, effects_intensity="high", match="cuts",
                  logo=False, title_text="")
    plan = plan_for(proj)
    trans = [s["transition"]["type"] for s in plan["shots"][1:]]
    assert sum(t != "cut" for t in trans) >= 0.4 * len(trans), trans
    assert plan["grade"] is None, "match=cuts must not colour-grade"
    assert plan["logo"] is None and plan["title"] is None

    proj2 = tmp_path / "col"
    basic_project(proj2, n_clips=4, match="color", effects_intensity="medium")
    plan2 = plan_for(proj2)
    assert plan2["grade"] and plan2["grade"]["strength"] >= 0.9


def test_square_no_music_uses_reference_pace(tmp_path):
    proj = tmp_path / "sq"
    basic_project(proj, n_clips=3, aspect="1:1", music=False, ref_shot=0.75, bpm=120,
                  min_seconds=6, max_seconds=9, resolution=480)
    plan = plan_for(proj)
    assert (plan["width"], plan["height"]) == (480, 480)
    assert 6 <= plan["duration"] <= 9
    lens = [s["end"] - s["start"] for s in plan["shots"]]
    assert 0.4 <= float(np.median(lens)) <= 1.6, lens


def test_long_brief_repeats_clips(tmp_path):
    proj = tmp_path / "rep"
    basic_project(proj, n_clips=2, clip_dur=4, min_seconds=12, max_seconds=16)
    plan = plan_for(proj)
    assert plan["duration"] >= 12
    used = [s["clip"] for s in plan["shots"]]
    assert len(used) > 2 and len(set(used)) == 2


# ---------------------------------------------------------------- AB6

@pytest.fixture(scope="module")
def good(tmp_path_factory):
    proj = tmp_path_factory.mktemp("bad") / "p"
    basic_project(proj, n_clips=3)
    plan = plan_for(proj)
    return proj, plan


def expect_invalid(proj, plan, word):
    save_plan(proj, plan)
    for cmd in ("validate", "render"):
        r = tc(cmd, proj, ok=False)
        out = (r.stdout + r.stderr).lower()
        assert word in out, f"{cmd}: expected '{word}' in: {out[-600:]}"
        assert len(out.strip().splitlines()) <= 5


def test_invalid_missing_clip(good):
    proj, plan = good
    p = copy.deepcopy(plan)
    p["shots"][1]["clip"] = "footage/does_not_exist.mp4"
    expect_invalid(proj, p, "clip")


def test_invalid_out_past_clip(good):
    proj, plan = good
    p = copy.deepcopy(plan)
    p["shots"][0]["out"] = 999.0
    expect_invalid(proj, p, "out")


def test_invalid_negative_in(good):
    proj, plan = good
    p = copy.deepcopy(plan)
    p["shots"][0]["in"] = -1.0
    expect_invalid(proj, p, "in")


def test_invalid_overlap(good):
    proj, plan = good
    p = copy.deepcopy(plan)
    p["shots"][2]["start"] = p["shots"][1]["start"] - 0.3
    expect_invalid(proj, p, "overlap")


def test_invalid_length(good):
    proj, plan = good
    p = copy.deepcopy(plan)
    keep = p["shots"][:2]
    p["shots"] = keep
    p["duration"] = keep[-1]["end"]
    expect_invalid(proj, p, "length")


def test_invalid_json_and_missing_field(good):
    proj, plan = good
    (proj / "work" / "plan.json").write_text("{not json")
    r = tc("validate", proj, ok=False)
    assert "plan.json" in (r.stdout + r.stderr)
    p = copy.deepcopy(plan)
    del p["shots"][0]["clip"]
    expect_invalid(proj, p, "clip")
    save_plan(proj, plan)
    tc("validate", proj)
