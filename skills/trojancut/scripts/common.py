"""Shared helpers: errors, ffmpeg/ffprobe, paths, brief loading, JSON I/O."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".3gp", ".wmv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff"}
FOLDERS = ("footage", "assets", "refs", "music", "sfx")


class Fail(Exception):
    """A user-facing failure: printed as one line, exit code 1."""


def fail(msg):
    raise Fail(msg)


def run(cmd, timeout=None, check=True, text=True, capture=True):
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=capture, text=text, timeout=timeout)
    except FileNotFoundError:
        fail(f"{cmd[0]} is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        fail(f"{Path(str(cmd[0])).name} timed out after {timeout}s")
    if check and r.returncode != 0:
        err = (r.stderr or "").strip().splitlines() if text else []
        fail(f"{Path(str(cmd[0])).name} failed: {err[-1] if err else 'exit ' + str(r.returncode)}")
    return r


def ffmpeg(*args, timeout=None):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], timeout=timeout)


def ffprobe(path):
    r = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path], check=False)
    if r.returncode != 0:
        fail(f"cannot read {Path(path).name}: not a media file ffprobe understands")
    return json.loads(r.stdout)


def fps_of(stream):
    for key in ("avg_frame_rate", "r_frame_rate"):
        v = stream.get(key, "0/0")
        try:
            n, d = v.split("/")
            if float(d) and float(n):
                return float(n) / float(d)
        except ValueError:
            pass
    return 0.0


def media_info(path):
    """Duration, size, fps and audio presence for a video, image or audio file."""
    info = ffprobe(path)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = 0.0
    for src in (info.get("format", {}), v or {}, a or {}):
        try:
            dur = max(dur, float(src.get("duration", 0) or 0))
        except ValueError:
            pass
    out = {"duration": round(dur, 3), "has_audio": a is not None}
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        rot = int(v.get("tags", {}).get("rotate", rot) or rot)
        if abs(rot) % 180 == 90:
            w, h = h, w
        out.update(width=w, height=h, fps=round(fps_of(v), 3))
    return out


def project_dir(p, must_exist=True):
    p = Path(p).resolve()
    if must_exist and not p.is_dir():
        fail(f"project folder not found: {p}")
    return p


def rel(p, proj):
    return Path(p).resolve().relative_to(Path(proj).resolve()).as_posix()


def write_json(path, data, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        path.write_text(json.dumps(data, separators=(",", ":")))
    else:
        path.write_text(json.dumps(data, indent=1))


def read_json(path, what=None):
    path = Path(path)
    if not path.exists():
        fail(f"{what or path.name} not found; run the earlier step first ({path})")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        fail(f"{path.name} is not valid JSON (line {e.lineno}): {e.msg}")


BRIEF_DEFAULTS = {
    "min_seconds": 15, "max_seconds": 30, "aspect": "9:16", "resolution": 1080, "fps": 30,
    "music": "none", "match": "full", "logo": "", "logo_position": "top-right", "title_text": "",
    "captions": False, "effects_intensity": "medium", "must_include": [], "avoid": [], "notes": "",
    "song_switch": "auto", "keep_clip_audio": False, "sfx_amount": "some", "sfx_source": "both",
}
ASPECTS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}


def load_brief(proj):
    import yaml
    p = Path(proj) / "brief.yaml"
    if not p.exists():
        fail(f"brief.yaml not found in {proj} (run `tc.py open` on the project zip, or write one)")
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        fail(f"brief.yaml is not valid YAML: {str(e).splitlines()[0]}")
    if not isinstance(data, dict):
        fail("brief.yaml must be a mapping of keys to values")
    b = dict(BRIEF_DEFAULTS)
    b.update({k: v for k, v in data.items() if v is not None})
    for k in ("min_seconds", "max_seconds", "resolution", "fps"):
        try:
            b[k] = float(b[k]) if k.endswith("seconds") else int(b[k])
        except (TypeError, ValueError):
            fail(f"brief.yaml {k} must be a number, got {b[k]!r}")
    if b["min_seconds"] <= 0 or b["max_seconds"] < b["min_seconds"]:
        fail(f"brief.yaml min_seconds/max_seconds out of order ({b['min_seconds']} > {b['max_seconds']})")
    if str(b["aspect"]) not in ASPECTS:
        fail(f"brief.yaml aspect must be one of {', '.join(ASPECTS)}, got {b['aspect']!r}")
    b["aspect"] = str(b["aspect"])
    if b["match"] not in ("full", "cuts", "color", "text"):
        fail(f"brief.yaml match must be full, cuts, color or text, got {b['match']!r}")
    if b["effects_intensity"] not in ("low", "medium", "high"):
        fail(f"brief.yaml effects_intensity must be low, medium or high, got {b['effects_intensity']!r}")
    if b["sfx_amount"] not in ("none", "some", "lots"):
        fail(f"brief.yaml sfx_amount must be none, some or lots, got {b['sfx_amount']!r}")
    if b["sfx_source"] not in ("built-in", "mine", "both"):
        fail(f"brief.yaml sfx_source must be built-in, mine or both, got {b['sfx_source']!r}")
    if b["song_switch"] not in ("cut", "fade", "auto"):
        fail(f"brief.yaml song_switch must be cut, fade or auto, got {b['song_switch']!r}")
    b["keep_clip_audio"] = bool(b["keep_clip_audio"])
    return b


def output_size(brief):
    """(width, height) for the brief: `resolution` is the short side, both even."""
    aw, ah = ASPECTS[brief["aspect"]]
    short = int(brief["resolution"])
    if aw <= ah:
        w, h = short, short * ah / aw
    else:
        w, h = short * aw / ah, short
    return int(round(w / 2) * 2), int(round(h / 2) * 2)


def tc_home():
    env = os.environ.get("TROJANCUT_HOME")
    if env:
        return Path(env)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "TrojanCut"
    return Path.home() / ".cache" / "trojancut"


def which(name):
    return shutil.which(name)


def log(msg):
    print(msg, file=sys.stderr, flush=True)
