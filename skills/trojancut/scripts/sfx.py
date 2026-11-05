"""Sound-effect placement: whooshes on transitions, hits on the title and strong beats, risers into song
switches. "some" ~ 1 per 4 cuts, "lots" ~ 1 per 2; never overlapping; mixed ~6 dB under the music."""
import json

from common import SKILL_DIR, log, rel

BUILTIN = SKILL_DIR / "sfx"
GAIN_DB = -6.0
FAMILY = {"whoosh": ["whoosh", "swoosh"], "swoosh": ["swoosh", "whoosh"], "impact": ["impact", "boom", "hit"],
          "hit": ["hit", "impact", "boom", "click"], "riser": ["riser"], "pop": ["pop", "click", "hit"],
          "glitch": ["glitch"], "shutter": ["shutter", "click"], "subdrop": ["subdrop", "drop", "boom"]}


def library(brief, idx, proj):
    """{type: [ {file, duration} ]} from the chosen source; 'both' puts the user's files first."""
    lib = {}
    src = brief["sfx_source"]
    if src in ("mine", "both"):
        for e in idx.get("sfx", []):
            lib.setdefault(e["type"], []).append({"file": e["path"], "duration": e["duration"]})
    if src in ("built-in", "both") or (src == "mine" and not lib):
        if src == "mine":
            log("no sound effects in sfx/, using the built-in pack")
        man = json.loads((BUILTIN / "manifest.json").read_text())
        for s in man["sounds"]:
            lib.setdefault(s["type"], []).append({"file": (BUILTIN / s["name"]).as_posix(), "duration": s["duration"]})
    return lib


def pick(lib, kind, n):
    for t in FAMILY.get(kind, [kind]):
        if lib.get(t):
            opts = lib[t]
            return t, opts[n % len(opts)]
    return None, None


def place(plan, brief, idx, proj):
    if brief["sfx_amount"] == "none":
        return []
    lib = library(brief, idx, proj)
    if not lib:
        return []
    shots = plan["shots"]
    cuts = len(shots) - 1
    target = max(1, round(cuts / (4 if brief["sfx_amount"] == "some" else 2)))
    events = []  # (start, end, item)
    counter = {}

    def add(kind, at, reason, end_at=False):
        t, item = pick(lib, kind, counter.get(kind, 0))
        if not item:
            return False
        counter[kind] = counter.get(kind, 0) + 1
        d = float(item["duration"])
        if t == "riser" or end_at:
            start = max(0.0, at - d)
        elif t in ("whoosh", "swoosh"):
            start = max(0.0, at - d / 2)
        else:
            start = at
        end = min(plan["duration"], start + d)
        if end - start < 0.08:
            return False
        if any(not (end + 0.05 <= a or start >= b + 0.05) for a, b, _ in events):
            return False
        events.append((start, end, {"file": item["file"], "type": t, "start": round(start, 4), "at": round(at, 4),
                                    "duration": round(end - start, 4), "gain_db": GAIN_DB, "reason": reason}))
        return True

    # 1. title reveal
    if plan.get("title"):
        add("impact", plan["title"]["start"] + 0.05, "title reveal")
    # 2. risers into song switches
    for sw in plan["music"].get("switches", []):
        if len(events) < target:
            add("riser", sw["at"], f"song switch ({sw['type']})", end_at=True)
    # 3. whooshes on soft transitions
    for s in shots[1:]:
        if len(events) >= target:
            break
        if s["transition"]["type"] != "cut":
            add("whoosh", s["start"], f"{s['transition']['type']} transition")
    # 4. hits on strong beats (cuts on bar lines first), evenly spread
    if len(events) < target:
        cut_times = [s["start"] for s in shots[1:] if s["transition"]["type"] == "cut"]
        need = target - len(events)
        step = max(1, len(cut_times) // max(1, need))
        order = cut_times[::step] + [c for c in cut_times if c not in cut_times[::step]]
        for k, c in enumerate(order):
            if len(events) >= target:
                break
            add("hit" if k % 3 else "impact", c, "strong beat at a cut")
    return [e for _, _, e in sorted(events, key=lambda e: e[0])]


def resolve(path, proj):
    """An sfx file path from plan.json: absolute (built-in) or relative to the project."""
    from pathlib import Path
    p = Path(path)
    return p if p.is_absolute() else Path(proj) / p
