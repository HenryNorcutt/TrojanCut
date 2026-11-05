"""`ingest P`: extract zips, index media, motion score, contact sheets (Claude's view of the footage)."""
import math
import re
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image

from common import (AUDIO_EXT, FOLDERS, IMAGE_EXT, VIDEO_EXT, fail, ffmpeg, log, media_info, project_dir, rel,
                    write_json)

SHEET_MAX = 1024           # longest side of any image Claude sees
MAX_TILES = 16
INDEX_IMAGE_BUDGET = 28     # of the 40 shared with style.json
SFX_TYPES = ["whoosh", "swoosh", "riser", "impact", "hit", "boom", "subdrop", "drop", "glitch", "pop", "click",
             "shutter", "snap", "swipe", "transition", "rise", "sweep", "thud", "slam", "punch", "camera", "zap"]
SFX_ALIASES = {"rise": "riser", "sweep": "whoosh", "swipe": "swoosh", "thud": "impact", "slam": "impact",
               "punch": "hit", "camera": "shutter", "snap": "click", "zap": "glitch", "transition": "whoosh",
               "subdrop": "subdrop", "drop": "drop"}


def junk(name):
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(p == "__MACOSX" or p.startswith(".") for p in parts)


def safe_extract(zpath, dest):
    """Extract a zip into dest without path traversal, skipping macOS junk and dotfiles."""
    dest = Path(dest).resolve()
    try:
        zf = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        fail(f"{Path(zpath).name} is not a readable zip file")
    with zf:
        for info in zf.infolist():
            if info.is_dir() or junk(info.filename):
                continue
            target = (dest / info.filename.replace("\\", "/")).resolve()
            if dest not in target.parents:
                fail(f"{Path(zpath).name} contains an unsafe path: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def extract_zips(proj):
    """Extract every .zip under the media folders into <folder>/<zipname>/ and move the zip to work/zips."""
    done = proj / "work" / "zips"
    for folder in FOLDERS:
        d = proj / folder
        while d.is_dir():
            zips = [z for z in d.rglob("*.zip") if not junk(z.name)]
            if not zips:
                break
            for z in zips:
                target = z.parent / z.stem
                log(f"extracting {rel(z, proj)}")
                safe_extract(z, target)
                done.mkdir(parents=True, exist_ok=True)
                shutil.move(str(z), str(done / f"{folder}__{z.name}"))


def media_files(proj, folder, exts):
    d = proj / folder
    if not d.is_dir():
        return []
    return sorted((p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts and not junk(p.name)),
                  key=lambda p: rel(p, proj).lower())


def gray_frames(path, dur, n=12, size=64):
    """n evenly spaced grey thumbnails (size x size) as float arrays."""
    if dur <= 0:
        return []
    fps = n / dur
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                        f"fps={fps:.6f},scale={size}:{size}:flags=area,format=gray", "-frames:v", str(n),
                        "-f", "rawvideo", "-"], capture_output=True)
    raw = r.stdout
    k = len(raw) // (size * size)
    return [np.frombuffer(raw[i * size * size:(i + 1) * size * size], np.uint8).astype(np.float64)
            for i in range(k)]


def colour_stats(path, dur, n=8):
    """Mean and std of RGB over n sampled frames (0-255)."""
    if dur <= 0:
        return None
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                        f"fps={n / dur:.6f},scale=48:48:flags=area,format=rgb24", "-frames:v", str(n),
                        "-f", "rawvideo", "-"], capture_output=True)
    px = np.frombuffer(r.stdout, np.uint8).reshape(-1, 3).astype(np.float64)
    if not len(px):
        return None
    return {"mean_rgb": [round(float(v), 1) for v in px.mean(0)], "std_rgb": [round(float(v), 1) for v in px.std(0)]}


def motion_score(path, dur):
    """Mean absolute difference between consecutive sampled grey frames, 0-100."""
    fr = gray_frames(path, dur, n=16, size=48)
    if len(fr) < 2:
        return 0.0
    return round(float(np.mean([np.abs(a - b).mean() for a, b in zip(fr, fr[1:])])) / 2.55, 2)


def contact_sheet(path, dur, out, tiles, tile_w=256):
    """One grid image of `tiles` evenly spaced frames with timestamps, longest side <= 1024."""
    from PIL import ImageDraw
    tiles = max(1, min(MAX_TILES, tiles))
    cols = min(4, tiles)
    rows = math.ceil(tiles / cols)
    times = [dur * (i + 0.5) / tiles for i in range(tiles)]
    frames = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                            "-vf", f"scale={tile_w}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True)
        if r.returncode == 0 and r.stdout:
            import io
            frames.append((t, Image.open(io.BytesIO(r.stdout)).convert("RGB")))
    if not frames:
        return False
    th = max(f.height for _, f in frames)
    sheet = Image.new("RGB", (cols * tile_w, rows * th), (16, 16, 16))
    d = ImageDraw.Draw(sheet)
    for i, (t, f) in enumerate(frames):
        x, y = (i % cols) * tile_w, (i // cols) * th
        sheet.paste(f, (x, y))
        d.rectangle([x, y, x + 46, y + 14], fill=(0, 0, 0))
        d.text((x + 3, y + 2), f"{t:5.1f}s", fill=(255, 255, 0))
    sheet.thumbnail((SHEET_MAX, SHEET_MAX))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=80)
    return True


def group_sheet(items, out):
    """One overview image of several clips (one middle frame each, labelled)."""
    from PIL import ImageDraw
    cols = min(4, len(items))
    rows = math.ceil(len(items) / cols)
    tw = 256
    tiles = []
    for proj_path, label, dur in items:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur / 2:.3f}", "-i", str(proj_path), "-frames:v", "1",
                            "-vf", f"scale={tw}:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        import io
        img = Image.open(io.BytesIO(r.stdout)).convert("RGB") if r.returncode == 0 and r.stdout else \
            Image.new("RGB", (tw, 144))
        tiles.append((label, img))
    th = max(i.height for _, i in tiles)
    sheet = Image.new("RGB", (cols * tw, rows * th), (16, 16, 16))
    d = ImageDraw.Draw(sheet)
    for k, (label, img) in enumerate(tiles):
        x, y = (k % cols) * tw, (k // cols) * th
        sheet.paste(img, (x, y))
        d.rectangle([x, y, x + 7 * len(label) + 6, y + 14], fill=(0, 0, 0))
        d.text((x + 3, y + 2), label, fill=(255, 255, 0))
    sheet.thumbnail((SHEET_MAX, SHEET_MAX))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=80)


def sfx_type_from_name(name):
    stem = re.sub(r"[^a-z]+", " ", Path(name).stem.lower())
    words = stem.split()
    joined = "".join(words)
    for t in SFX_TYPES:
        if t in words or (len(t) >= 4 and t in joined):
            return SFX_ALIASES.get(t, t)
    return None


def index_sfx(proj, files):
    from audio import classify_shape, decode, rms_db
    out = []
    for p in files:
        x = decode(p, sr=22050)
        t = sfx_type_from_name(p.name)
        out.append({"path": rel(p, proj), "type": t or classify_shape(x), "type_from": "name" if t else "shape",
                    "duration": round(len(x) / 22050, 3), "loudness_db": round(rms_db(x), 1),
                    "peak_db": round(20 * math.log10(float(np.max(np.abs(x))) + 1e-9), 1) if len(x) else -120.0})
    return out


def ingest(proj):
    proj = project_dir(proj)
    work = proj / "work"
    work.mkdir(exist_ok=True)
    extract_zips(proj)
    sheets_dir = work / "sheets"
    if sheets_dir.exists():
        shutil.rmtree(sheets_dir)

    clips, images, refs, music = [], [], [], []
    for folder in ("footage", "assets"):
        for p in media_files(proj, folder, IMAGE_EXT):
            im = Image.open(p)
            images.append({"path": rel(p, proj), "width": im.width, "height": im.height,
                           "alpha": im.mode in ("RGBA", "LA", "P")})
    for p in media_files(proj, "footage", VIDEO_EXT):
        info = media_info(p)
        if "width" not in info or info["duration"] <= 0.2:
            log(f"skipping {rel(p, proj)}: no usable video stream")
            continue
        clips.append({"path": rel(p, proj), **info, "motion": motion_score(p, info["duration"]),
                      "color": colour_stats(p, info["duration"])})
    for p in media_files(proj, "refs", VIDEO_EXT):
        info = media_info(p)
        if "width" in info:
            refs.append({"path": rel(p, proj), **info})
    for p in media_files(proj, "music", AUDIO_EXT | VIDEO_EXT):
        info = media_info(p)
        if info["has_audio"]:
            music.append({"path": rel(p, proj), "duration": info["duration"]})
    sfx = index_sfx(proj, media_files(proj, "sfx", AUDIO_EXT))

    # Contact sheets: one per clip when they fit the budget; otherwise one per clip for the
    # first clips plus grouped overview sheets for the rest.
    claude = []
    n = len(clips)
    if n <= INDEX_IMAGE_BUDGET:
        per_clip = clips
        grouped = []
    else:
        groups_needed = lambda k: math.ceil((n - k) / 16)
        k = INDEX_IMAGE_BUDGET
        while k > 0 and k + groups_needed(k) > INDEX_IMAGE_BUDGET:
            k -= 1
        per_clip, grouped = clips[:k], clips[k:]
    for i, c in enumerate(per_clip):
        tiles = int(min(MAX_TILES, max(4, round(c["duration"] / 1.0))))
        tiles = 16 if tiles > 12 else 12 if tiles > 9 else 9 if tiles > 6 else tiles
        out = sheets_dir / f"clip{i + 1:03d}.jpg"
        if contact_sheet(proj / c["path"], c["duration"], out, tiles):
            c["sheet"], c["sheet_tiles"] = rel(out, proj), tiles
            claude.append(c["sheet"])
    for g in range(0, len(grouped), 16):
        chunk = grouped[g:g + 16]
        out = sheets_dir / f"group{g // 16 + 1:02d}.jpg"
        base = len(per_clip) + g
        group_sheet([(proj / c["path"], f"#{base + j + 1}", c["duration"]) for j, c in enumerate(chunk)], out)
        for j, c in enumerate(chunk):
            c["sheet"], c["sheet_tiles"] = rel(out, proj), len(chunk)
            c["sheet_label"] = f"#{base + j + 1}"
        claude.append(rel(out, proj))

    index = {"version": 1, "clips": clips, "images": images, "refs": refs, "music": music, "sfx": sfx,
             "claude_images": claude}
    write_json(work / "index.json", index, compact=n > 12)
    print(f"indexed {len(clips)} clips, {len(images)} images, {len(refs)} references, {len(music)} songs, "
          f"{len(sfx)} sound effects; {len(claude)} contact sheets -> work/index.json")
