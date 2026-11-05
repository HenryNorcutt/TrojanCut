"""`template --out D` (the TrojanCut-Project.zip the user fills in) and `open ZIP... P` (unpack + notes.txt ->
brief.yaml). brief.yaml stays the internal format the other commands read."""
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import yaml

from common import AUDIO_EXT, FOLDERS, IMAGE_EXT, VIDEO_EXT, fail, log
from ingest import junk, safe_extract

ZIP_NAME = "TrojanCut-Project.zip"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)

READMES = {
    "footage": "Put your clips here (phone videos, camera files, screen recordings; zips are fine).",
    "assets": "Put logos and images here (PNG with a transparent background works best for a logo).",
    "refs": "Put the videos whose style you want copied here (cuts, colour, text, effects).",
    "music": "Optional: put the song(s) for the edit here (mp3, wav, m4a). Leave empty to use none or the reference audio.",
    "sfx": "Optional: put your own sound effects here and put the type in the file name, e.g. whoosh_big.wav, impact_1.mp3, riser.wav.",
}

HOW_TO = """TrojanCut project - how to use it

1. Put your clips in footage, logos/images in assets, the videos to copy the style of in refs,
   and (optional) your song(s) in music and your own sound effects in sfx.
2. Open notes.txt, answer each line after the colon and save. Blank = let Claude decide.
   Anything else you want goes on the lines under the last question.
3. Zip the folder: right-click the TrojanCut-Project folder > Compress to ZIP file (Windows 11),
   or Send to > Compressed (zipped) folder (Windows 10).
4. Open a new Claude chat, type /trojancut, attach the zip and send.
5. Wait while it analyses and renders, then download the MP4. Reply with changes if you want any.

Keep each zip under 500 MB. For a big shoot, make several zips (for example, move half the footage
into a second copy of this folder) and attach them together in the same message.
"""

# (key, question text, default answer)
QUESTIONS = [
    ("shortest", "Shortest length in seconds", "15"),
    ("longest", "Longest length in seconds", "30"),
    ("shape", "Shape (vertical / horizontal / square)", "vertical"),
    ("music", "Music (none / reference audio / my songs)", "my songs"),
    ("song_order", "Song order (file names separated by ;  blank = alphabetical)", ""),
    ("song_parts", "Song parts (e.g. song1.mp3 0:45-1:15; song2.mp3 auto  blank = Claude picks)", ""),
    ("switch", "Switch between songs (cut / quick fade / Claude decides)", "Claude decides"),
    ("keep_sound", "Keep sound from the clips (yes / no)", "no"),
    ("sfx_amount", "Sound effects (none / some / lots)", "some"),
    ("sfx_source", "Which sound effects (built-in / mine / both)", "both"),
    ("copy", "Copy from the references (cuts / color / text / everything)", "everything"),
    ("effects", "Effects amount (low / medium / high)", "medium"),
    ("logo", "Logo file (name in assets folder)", ""),
    ("corner", "Logo corner (top-left / top-right / bottom-left / bottom-right / none)", "top-right"),
    ("title", "Title text at the start (blank = none)", ""),
    ("must", "Must include", ""),
    ("avoid", "Avoid", ""),
    ("else", "Anything else (any notes or context, as many lines as you like below this one)", ""),
]
DEFAULTS = {k: d for k, _, d in QUESTIONS}

# leading words (before any parenthesis) -> key; older template wordings included
LEADS = [
    ("shortest length", "shortest"), ("shortest", "shortest"), ("min length", "shortest"),
    ("longest length", "longest"), ("longest", "longest"), ("max length", "longest"),
    ("shape", "shape"), ("aspect", "shape"),
    ("music file", "music_file"), ("music", "music"),
    ("song order", "song_order"), ("song parts", "song_parts"), ("switch between songs", "switch"),
    ("keep sound", "keep_sound"),
    ("sound effects", "sfx_amount"), ("which sound effects", "sfx_source"),
    ("copy from", "copy"), ("effects amount", "effects"), ("effects", "effects"),
    ("logo file", "logo"), ("logo corner", "corner"), ("logo position", "corner"),
    ("title text", "title"), ("title", "title"), ("must include", "must"), ("avoid", "avoid"),
    ("anything else", "else"),
]


def template_bytes():
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def add(name, text):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, text.replace("\n", "\r\n"))
        add("HOW-TO.txt", HOW_TO)
        add("notes.txt", "".join(f"{q}: {d}\n" for _, q, d in QUESTIONS))
        for f in FOLDERS:
            add(f"{f}/README.txt", READMES[f] + "\n")
    return buf.getvalue()


def write_template(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ZIP_NAME).write_bytes(template_bytes())
    print(f"wrote {out / ZIP_NAME}")


# ---------------------------------------------------------------- notes.txt parsing

def split_qa(line):
    """Question and answer split at the first colon outside parentheses (questions may hold 0:45)."""
    depth = 0
    for i, ch in enumerate(line):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            return line[:i], line[i + 1:]
    return None


def key_for(question):
    lead = re.sub(r"\s+", " ", question.split("(")[0]).strip().lower()
    for words, key in LEADS:
        if lead == words or lead.startswith(words + " ") or (lead.startswith(words) and len(words) > 6):
            return key
    return None


def parse_notes(text):
    """{key: answer} plus the free text after the 'Anything else' line (verbatim)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    answers, notes = {}, ""
    for n, line in enumerate(lines):
        qa = split_qa(line)
        if not qa:
            continue
        key = key_for(qa[0])
        if key is None:
            continue
        if key == "else":
            first = qa[1].strip()
            rest = "\n".join(lines[n + 1:]).rstrip("\n")
            notes = "\n".join(x for x in (first, rest) if x) if first else rest
            break
        if key not in answers:
            answers[key] = qa[1].strip()
    return answers, notes


# ---------------------------------------------------------------- mapping

def parse_time(v, what):
    v = v.strip()
    m = re.fullmatch(r"(\d+):(\d{1,2}(?:\.\d+)?)", v)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(v)
    except ValueError:
        fail(f"notes.txt: cannot read the time '{v}' in {what} (use 1:15, 01:15 or 75)")


def num(v):
    return int(v) if float(v).is_integer() else float(v)


def choice(answer, options, question, default):
    a = re.sub(r"\s+", " ", (answer or "").strip().lower())
    if not a:
        return default
    for k, v in options.items():
        if a == k:
            return v
    for k, v in options.items():
        if a.startswith(k) or k.startswith(a):
            return v
    fail(f"notes.txt: '{answer.strip()}' is not one of the choices for '{question}' ({' / '.join(options)})")


def find_file(proj, folder, name, exts):
    name = name.strip().strip('"').strip("'")
    if not name:
        return None
    d = proj / folder
    cands = [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else []
    for p in cands:
        if p.name.lower() == name.lower() or p.relative_to(d).as_posix().lower() == name.lower():
            return p.relative_to(proj).as_posix()
    for p in cands:
        if p.stem.lower() == Path(name).stem.lower() and p.suffix.lower() in exts:
            return p.relative_to(proj).as_posix()
    return None


def media(proj, folder, exts):
    d = proj / folder
    if not d.is_dir():
        return []
    return sorted((p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts and not junk(p.name)),
                  key=lambda p: p.relative_to(proj).as_posix().lower())


def words_list(v):
    return [w.strip() for w in re.split(r"[;,\n]", v or "") if w.strip()]


def to_brief(a, notes, proj):
    b = {}
    get = lambda k: a.get(k, DEFAULTS.get(k, "")) if a.get(k, "").strip() else DEFAULTS.get(k, "")
    try:
        lo = float(get("shortest") or 15)
    except ValueError:
        fail(f"notes.txt: Shortest length '{a.get('shortest')}' is not a number of seconds")
    try:
        hi = float(get("longest") or 30)
    except ValueError:
        fail(f"notes.txt: Longest length '{a.get('longest')}' is not a number of seconds")
    if lo <= 0 or hi <= 0:
        fail("notes.txt: lengths must be more than 0 seconds")
    if lo > hi:
        fail(f"notes.txt: Shortest length ({lo:g}s) is longer than Longest length ({hi:g}s)")
    b["min_seconds"], b["max_seconds"] = num(lo), num(hi)
    b["aspect"] = choice(get("shape"), {"vertical": "9:16", "horizontal": "16:9", "square": "1:1",
                                        "portrait": "9:16", "landscape": "16:9", "9:16": "9:16", "16:9": "16:9",
                                        "1:1": "1:1"}, "Shape", "9:16")
    b["resolution"] = 1080
    b["fps"] = 30

    songs = media(proj, "music", AUDIO_EXT | VIDEO_EXT)
    if a.get("music_file", "").strip() and "music" not in a:  # older template: "Music file: name"
        mf = a["music_file"].strip()
        if mf.lower() in ("reference audio", "reference", "none"):
            a["music"] = mf
        else:
            a["music"], a["song_order"] = "my songs", mf
    mode = choice(get("music"), {"none": "none", "no": "none", "reference audio": "reference",
                                 "reference": "reference", "my songs": "songs", "songs": "songs", "mine": "songs"},
                  "Music", "songs")
    switch = choice(get("switch"), {"cut": "cut", "quick fade": "fade", "fade": "fade", "claude decides": "auto",
                                    "auto": "auto"}, "Switch between songs", "auto")
    keep = choice(get("keep_sound"), {"yes": True, "no": False, "y": True, "n": False}, "Keep sound from the clips",
                  False)
    if mode == "none":
        b["music"] = "none"
    elif mode == "reference":
        b["music"] = "reference"
    else:
        if not songs:
            fail("notes.txt says Music: my songs, but the music folder is empty - add a song or answer none / "
                 "reference audio")
        order = []
        for name in [w for w in (a.get("song_order") or "").split(";") if w.strip()]:
            f = find_file(proj, "music", name, AUDIO_EXT | VIDEO_EXT)
            if not f:
                fail(f"notes.txt: Song order names '{name.strip()}' but there is no such file in the music folder")
            if f not in order:
                order.append(f)
        for p in songs:
            rp = p.relative_to(proj).as_posix()
            if rp not in order:
                order.append(rp)
        parts = {}
        for item in [w for w in (a.get("song_parts") or "").split(";") if w.strip()]:
            m = re.fullmatch(r"\s*(.+?)\s+(auto|[\d:.]+\s*-\s*[\d:.]+)\s*", item, re.I)
            if not m:
                fail(f"notes.txt: cannot read the song part '{item.strip()}' (use: song.mp3 0:45-1:15 or song.mp3 auto)")
            f = find_file(proj, "music", m.group(1), AUDIO_EXT | VIDEO_EXT)
            if not f:
                fail(f"notes.txt: Song parts names '{m.group(1)}' but there is no such file in the music folder")
            if m.group(2).lower() == "auto":
                parts[f] = "auto"
            else:
                s0, s1 = [parse_time(x, f"Song parts for {m.group(1)}") for x in m.group(2).split("-")]
                if s1 <= s0:
                    fail(f"notes.txt: the part for {m.group(1)} ends before it starts ({m.group(2)})")
                parts[f] = [num(s0), num(s1)]
        if len(order) == 1 and order[0] not in parts:
            b["music"] = order[0]
        elif len(order) == 1 and parts.get(order[0]) == "auto":
            b["music"] = order[0]
        else:
            b["music"] = [{"file": f, "part": parts.get(f, "auto")} for f in order]
    b["song_switch"] = switch
    b["keep_clip_audio"] = keep

    b["sfx_amount"] = choice(get("sfx_amount"), {"none": "none", "some": "some", "lots": "lots", "no": "none"},
                             "Sound effects", "some")
    src = choice(get("sfx_source"), {"built-in": "built-in", "builtin": "built-in", "mine": "mine", "both": "both"},
                 "Which sound effects", "both")
    if src in ("mine", "both") and not media(proj, "sfx", AUDIO_EXT):
        if b["sfx_amount"] != "none":
            log(f"note: sound effects '{src}' but the sfx folder is empty, so the built-in sounds are used")
        src = "built-in"
    b["sfx_source"] = src
    b["match"] = choice(get("copy"), {"everything": "full", "cuts": "cuts", "color": "color", "colour": "color",
                                      "text": "text", "all": "full"}, "Copy from the references", "full")
    b["effects_intensity"] = choice(get("effects"), {"low": "low", "medium": "medium", "high": "high"},
                                    "Effects amount", "medium")
    logo_ans = (a.get("logo") or "").strip()
    images = media(proj, "assets", IMAGE_EXT)
    if logo_ans:
        f = find_file(proj, "assets", logo_ans, IMAGE_EXT)
        if not f:
            fail(f"notes.txt: Logo file '{logo_ans}' is not in the assets folder")
        b["logo"] = f
    elif len(images) == 1:
        b["logo"] = images[0].relative_to(proj).as_posix()
        log(f"note: using {b['logo']} as the logo (the only image in assets)")
    else:
        b["logo"] = ""
    b["logo_position"] = choice(get("corner"), {"top-left": "top-left", "top-right": "top-right",
                                                "bottom-left": "bottom-left", "bottom-right": "bottom-right",
                                                "none": "none", "top left": "top-left", "top right": "top-right",
                                                "bottom left": "bottom-left", "bottom right": "bottom-right"},
                                "Logo corner", "top-right")
    b["title_text"] = (a.get("title") or "").strip()
    b["captions"] = False
    b["must_include"] = words_list(a.get("must"))
    b["avoid"] = words_list(a.get("avoid"))
    b["notes"] = notes
    return b


# ---------------------------------------------------------------- open

def project_root(tmp):
    """The folder inside an extracted zip that holds the project (root or one wrapper folder)."""
    def is_root(d):
        return any((d / f).is_dir() for f in FOLDERS) or (d / "notes.txt").is_file()
    if is_root(tmp):
        return tmp
    subs = [d for d in tmp.iterdir() if d.is_dir() and not junk(d.name)]
    for d in subs:
        if is_root(d):
            return d
    if len(subs) == 1:
        inner = [d for d in subs[0].iterdir() if d.is_dir()]
        for d in inner:
            if is_root(d):
                return d
    return tmp


def merge_into(src, dest):
    for p in sorted(src.rglob("*")):
        if not p.is_file() or junk(p.relative_to(src).as_posix()):
            continue
        rel = p.relative_to(src)
        target = dest / rel
        if target.exists():
            if target.read_bytes() == p.read_bytes() or rel.name == "README.txt":
                continue
            if rel.as_posix() in ("notes.txt", "HOW-TO.txt"):
                continue  # the first zip's notes win
            k = 2
            while (target.parent / f"{target.stem}_{k}{target.suffix}").exists():
                k += 1
            target = target.parent / f"{target.stem}_{k}{target.suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


def open_project(sources, proj):
    proj = Path(proj).resolve()
    proj.mkdir(parents=True, exist_ok=True)
    stage = proj / "work" / "unzip"
    if stage.exists():
        shutil.rmtree(stage)
    for k, src in enumerate(sources):
        src = Path(src)
        if not src.exists():
            fail(f"not found: {src}")
        if src.is_dir():
            root = project_root(src.resolve())
        else:
            if src.suffix.lower() != ".zip":
                fail(f"{src.name} is not a .zip file or a folder")
            d = stage / f"z{k}"
            safe_extract(src, d)
            root = project_root(d)
        if root.resolve() != proj:
            merge_into(root, proj)
    if stage.exists():
        shutil.rmtree(stage)
    notes_p = proj / "notes.txt"
    if notes_p.exists():
        answers, notes = parse_notes(notes_p.read_text(encoding="utf-8", errors="replace"))
    else:
        log("note: notes.txt is missing, so defaults are used (Claude may ask a few questions)")
        print("notes.txt missing: using defaults")
        answers, notes = {}, ""
    brief = to_brief(answers, notes, proj)
    (proj / "brief.yaml").write_text(yaml.safe_dump(brief, sort_keys=False, allow_unicode=True))
    counts = {f: len([p for p in (proj / f).rglob("*") if p.is_file() and p.name != "README.txt"])
              if (proj / f).is_dir() else 0 for f in FOLDERS}
    print("opened project: " + ", ".join(f"{v} in {k}" for k, v in counts.items()) + f" -> {proj / 'brief.yaml'}")
