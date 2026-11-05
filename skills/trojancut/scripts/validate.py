"""`validate P`: check work/plan.json against the footage, the brief and itself. One plain line per problem."""
from pathlib import Path

from common import Fail, fail, load_brief, project_dir, read_json

TOL = 0.02


def num(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(f"plan.json {where} must be a number, got {v!r}")
    return float(v)


def source_needed(length, keys):
    if not keys:
        return length
    ts = [0.0] + [num(k.get("t"), "speed t") for k in keys] + [length]
    vs = [keys[0]["speed"]] + [k["speed"] for k in keys] + [keys[-1]["speed"]]
    total = 0.0
    for (t0, v0), (t1, v1) in zip(zip(ts, vs), zip(ts[1:], vs[1:])):
        a, b = max(0.0, min(t0, length)), max(0.0, min(t1, length))
        total += (b - a) * (v0 + v1) / 2
    return total


def validate(proj, plan=None):
    proj = project_dir(proj)
    brief = load_brief(proj)
    if plan is None:
        plan = read_json(proj / "work" / "plan.json", "work/plan.json (run autoplan first)")
    idx = read_json(proj / "work" / "index.json", "work/index.json")
    clips = {c["path"]: c for c in idx["clips"]}
    if not isinstance(plan, dict):
        fail("plan.json must be an object")
    for k in ("width", "height", "fps", "duration", "shots"):
        if k not in plan:
            fail(f"plan.json is missing '{k}'")
    dur = num(plan["duration"], "duration")
    if not (brief["min_seconds"] - TOL <= dur <= brief["max_seconds"] + TOL):
        fail(f"plan.json duration {dur:.2f}s is outside the brief's length {brief['min_seconds']:g}-"
             f"{brief['max_seconds']:g}s")
    shots = plan["shots"]
    if not isinstance(shots, list) or not shots:
        fail("plan.json shots must be a non-empty list")
    prev_end = 0.0
    for i, s in enumerate(shots):
        w = f"shots[{i}]"
        for k in ("clip", "in", "out", "start", "end"):
            if k not in s:
                fail(f"plan.json {w} is missing '{k}'")
        c = clips.get(s["clip"])
        if c is None or not (proj / s["clip"]).exists():
            fail(f"plan.json {w}.clip '{s['clip']}' is not a clip in footage/ (see work/index.json)")
        a, b = num(s["in"], f"{w}.in"), num(s["out"], f"{w}.out")
        st, en = num(s["start"], f"{w}.start"), num(s["end"], f"{w}.end")
        if a < 0:
            fail(f"plan.json {w}.in is {a:.2f}s; it must be 0 or more")
        if b > c["duration"] + TOL:
            fail(f"plan.json {w}.out is {b:.2f}s but {s['clip']} is only {c['duration']:.2f}s long")
        if b <= a:
            fail(f"plan.json {w}.out ({b:.2f}) must be after in ({a:.2f})")
        if en <= st:
            fail(f"plan.json {w}.end ({en:.2f}) must be after start ({st:.2f})")
        if i == 0 and abs(st) > TOL:
            fail(f"plan.json shots[0].start must be 0, got {st:.2f}")
        if st < prev_end - TOL:
            fail(f"plan.json {w} overlaps the previous shot (starts {st:.2f}s, previous ends {prev_end:.2f}s)")
        if st > prev_end + TOL:
            fail(f"plan.json {w} leaves a gap before it ({prev_end:.2f}s to {st:.2f}s)")
        L = en - st
        keys = s.get("speed") or []
        for j, k in enumerate(keys):
            v = num(k.get("speed"), f"{w}.speed[{j}].speed")
            t = num(k.get("t"), f"{w}.speed[{j}].t")
            if not (0.2 <= v <= 4.0):
                fail(f"plan.json {w}.speed[{j}].speed is {v}x; speed must be between 0.2x and 4x")
            if not (-TOL <= t <= L + TOL):
                fail(f"plan.json {w}.speed[{j}].t {t:.2f}s is outside the shot (0-{L:.2f}s)")
        need = source_needed(L, keys)
        if keys:
            if a + need > c["duration"] + TOL:
                fail(f"plan.json {w} speed curve needs {need:.2f}s of source footage from {a:.2f}s but "
                     f"{s['clip']} is only {c['duration']:.2f}s long")
        elif abs((b - a) - L) > 0.05:
            fail(f"plan.json {w} in/out span {b - a:.2f}s must equal its length {L:.2f}s (no speed curve)")
        for j, e in enumerate(s.get("effects") or []):
            t, d = num(e.get("at"), f"{w}.effects[{j}].at"), num(e.get("duration"), f"{w}.effects[{j}].duration")
            if e.get("type") not in ("flash", "shake", "zoom"):
                fail(f"plan.json {w}.effects[{j}].type must be flash, shake or zoom, got {e.get('type')!r}")
            if t < st - TOL or t + d > en + TOL or d <= 0:
                fail(f"plan.json {w}.effects[{j}] effect ({t:.2f}s +{d:.2f}s) is outside the shot ({st:.2f}-{en:.2f}s)")
            num(e.get("strength"), f"{w}.effects[{j}].strength")
        tr = s.get("transition") or {"type": "cut", "duration": 0}
        td = num(tr.get("duration", 0), f"{w}.transition.duration")
        if i == 0 and tr.get("type", "cut") != "cut":
            fail("plan.json shots[0].transition must be a cut (nothing to transition from)")
        if td > 0 and (td > L / 2 + TOL or (i > 0 and td > (shots[i - 1]["end"] - shots[i - 1]["start"]) / 2 + TOL)):
            fail(f"plan.json {w}.transition.duration {td:.2f}s is longer than half a neighbouring shot")
        prev_end = en
    if abs(prev_end - dur) > 0.05:
        fail(f"plan.json shots end at {prev_end:.2f}s but duration is {dur:.2f}s (length mismatch)")
    from sfx import resolve
    for j, e in enumerate(plan.get("sfx") or []):
        f = e.get("file", "")
        if not f or not resolve(f, proj).exists():
            fail(f"plan.json sfx[{j}].file '{f}' does not exist")
        st = num(e.get("start"), f"sfx[{j}].start")
        d = num(e.get("duration"), f"sfx[{j}].duration")
        if st < -TOL or st + d > dur + 0.1:
            fail(f"plan.json sfx[{j}] runs outside the edit ({st:.2f}s +{d:.2f}s)")
    m = plan.get("music") or {}
    for j, sgm in enumerate(m.get("segments") or []):
        if not (proj / sgm.get("file", "")).exists():
            fail(f"plan.json music.segments[{j}].file '{sgm.get('file')}' does not exist")
    if plan.get("logo") and not (proj / plan["logo"].get("file", "")).exists():
        fail(f"plan.json logo.file '{plan['logo'].get('file')}' does not exist")
    if plan.get("grade") and not (proj / plan["grade"].get("lut", "")).exists():
        fail(f"plan.json grade.lut '{plan['grade'].get('lut')}' does not exist")
    return plan


def validate_cmd(proj):
    plan = validate(proj)
    print(f"plan.json OK: {len(plan['shots'])} shots, {plan['duration']:.2f}s")
