"""Shared helpers for the TrojanCut acceptance tests (plan pass; protected once building starts).

Synthetic media only: every clip, reference, song and sound is generated here with ffmpeg or
numpy, and every output is measured independently (ffprobe, decoded pixels, decoded audio).
"""
import json
import math
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / "skills" / "trojancut"
TC = SKILL / "scripts" / "tc.py"
SR = 22050

BASE_BRIEF = {
    "min_seconds": 10,
    "max_seconds": 14,
    "aspect": "16:9",
    "resolution": 360,
    "fps": 25,
    "music": "music/song.wav",
    "match": "full",
    "logo": "assets/logo.png",
    "logo_position": "top-right",
    "title_text": "HELLO",
    "captions": False,
    "effects_intensity": "low",
    "must_include": [],
    "avoid": [],
    "notes": "",
    "sfx_amount": "none",
    "sfx_source": "built-in",
}


# ---------------------------------------------------------------- running the CLI

def tc(*args, env=None, ok=True, timeout=30 * 60, cwd=None):
    """Run tc.py. ok=True asserts exit 0; ok=False asserts non-zero, a reason, and no traceback."""
    r = subprocess.run([sys.executable, str(TC), *map(str, args)], capture_output=True, text=True,
                       env=env, timeout=timeout, cwd=cwd)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, f"tc.py {' '.join(map(str, args))} exited {r.returncode}\n{out[-4000:]}"
    else:
        assert r.returncode != 0, f"tc.py {' '.join(map(str, args))} should have failed\n{out[-2000:]}"
        assert "Traceback" not in out, out[-3000:]
        assert out.strip(), "failure must print a reason"
    return r


def engine_env(engine, **extra):
    env = dict(os.environ, TROJANCUT_ENGINE=engine)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def path_without_node(tmp):
    """A PATH holding only python, ffmpeg and ffprobe (no node, npm, npx)."""
    bin_dir = Path(tmp) / "nonode-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("ffmpeg", "ffprobe", "unzip", "zip"):
        p = shutil.which(tool)
        if p and not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(p)
    py = bin_dir / "python3"
    if not py.exists():
        py.symlink_to(sys.executable)
    return str(bin_dir)


def run_pipeline(proj, env=None, steps=("ingest", "analyze-refs", "autoplan", "render", "check")):
    for s in steps:
        tc(s, proj, env=env)


# ---------------------------------------------------------------- ffmpeg / ffprobe

def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def vstream(path):
    return next(s for s in probe(path)["streams"] if s["codec_type"] == "video")


def has_audio(path):
    return any(s["codec_type"] == "audio" for s in probe(path)["streams"])


def duration(path):
    return float(probe(path)["format"]["duration"])


def frame(path, t, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", f"scale={w}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    assert len(raw) == w * h * 3, f"no frame at {t}s in {path}"
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.int32)


def magenta_mask(img):
    return (img[..., 0] > 190) & (img[..., 1] < 90) & (img[..., 2] > 190)


def scene_cuts(path, w=160, h=90, thr=0.15):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf",
                        f"scale={w}:{h},select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(line.split("pts_time:")[1].split()[0]) for line in r.stderr.splitlines() if "pts_time:" in line]


def image_size(path):
    s = vstream(path)
    return s["width"], s["height"]


# ---------------------------------------------------------------- synthetic media

def make_clip(path, colour, w=640, h=360, fps=25, dur=6.0, moving=True, tone=None, noise=False, audio_wav=None):
    """Solid-colour clip, optionally with a moving white box and a sine tone, noise or given wav track."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "lavfi", "-i", f"color=c=0x{colour}:s={w}x{h}:r={fps}:d={dur}"]
    if audio_wav:
        args += ["-i", str(audio_wav)]
    elif tone:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=44100:duration={dur}"]
    elif noise:
        args += ["-f", "lavfi", "-i", f"anoisesrc=a=0.05:d={dur}"]
    vf = []
    if moving:
        # overlay evaluates x per frame (drawbox in ffmpeg 6.1 evaluates it once, so it would not move)
        bw = max(8, w // 8)
        nin = 2 if (tone or noise or audio_wav) else 1
        args += ["-f", "lavfi", "-i", f"color=c=white:s={bw}x{bw}:r={fps}:d={dur}"]
        vf = ["-filter_complex", f"[0:v][{nin}:v]overlay=x='mod(t*{w // 3},{w - bw})':y={h // 3}:shortest=1[v]",
              "-map", "[v]"] + (["-map", "1:a"] if nin == 2 else [])
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", str(fps)]
    if tone or noise or audio_wav:
        ff(*args, *vf, *enc, "-c:a", "aac", "-b:a", "192k", "-shortest", path)
    else:
        ff(*args, *vf, *enc, path)


def make_ref(path, colours, shot, w=360, h=640, fps=25, n_shots=10, audio=None, moving=True):
    """Reference with a hard cut every `shot` seconds cycling through `colours`; optional audio file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.stem}_parts"
    tmp.mkdir(exist_ok=True)
    parts = []
    for k in range(n_shots):
        seg = tmp / f"s{k:03d}.mp4"
        c = colours[k % len(colours)]
        vf = ["-vf", f"drawbox=x='mod(t*{w // 2}\\,{w - w // 6})':y={h // 2}:w={w // 6}:h={w // 6}:color=white:t=fill"] if moving else []
        ff("-f", "lavfi", "-i", f"color=c=0x{c}:s={w}x{h}:r={fps}:d={shot}", *vf,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", seg)
        parts.append(seg)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    total = shot * n_shots
    if audio:
        ff("-f", "concat", "-safe", "0", "-i", lst, "-i", audio, "-t", f"{total:.3f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path)
    else:
        ff("-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-pix_fmt", "yuv420p", path)
    shutil.rmtree(tmp)


def write_wav(path, x, sr=44100):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(np.asarray(x, np.float64), -1, 1)
    pcm = (x * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def song_signal(bpm, dur, freq, sr=44100, offset=0.0, pad=0.15, burst=0.6, accent=True,
                section_step=0.0, section_len=5.0, loud=None, quiet_gain=0.12):
    """Synthetic song: a sustained pad plus a tone burst on every beat (bar downbeat louder).

    freq can step by `section_step` Hz every `section_len` s (so a position in the song is
    identifiable by pitch). `loud=(t0, t1)` makes only that window loud and busy (double-time
    bursts); the rest is scaled by quiet_gain.
    """
    t = np.arange(int(dur * sr)) / sr
    f = freq + section_step * np.floor(t / section_len)
    phase = 2 * np.pi * np.cumsum(f) / sr
    tone = np.sin(phase)
    period = 60.0 / bpm
    x = pad * tone
    rel = t - offset
    k = np.floor(rel / period)
    since = rel - k * period
    env = np.where(rel >= 0, np.exp(-since * 25.0) * np.minimum(1.0, since / 0.005), 0.0)
    if accent:
        env = env * np.where(np.mod(k, 4) == 0, 1.0, 0.55)
    x = x + burst * env * tone
    if loud:
        t0, t1 = loud
        inside = (t >= t0) & (t < t1)
        half = period / 2
        k2 = np.floor(rel / half)
        since2 = rel - k2 * half
        busy = 0.5 * np.exp(-since2 * 30.0) * np.minimum(1.0, since2 / 0.005) * np.sin(2 * np.pi * 2 * freq * t)
        x = np.where(inside, x + busy, x * quiet_gain)
    return x / max(1e-9, np.max(np.abs(x))) * 0.9


def make_song(path, bpm, dur, freq, **kw):
    write_wav(path, song_signal(bpm, dur, freq, **kw))


def make_logo(path, size=256, rgb=(255, 0, 255)):
    from PIL import Image
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (size, size), rgb).save(path)


def write_brief(proj, **over):
    b = dict(BASE_BRIEF)
    b.update(over)
    Path(proj).mkdir(parents=True, exist_ok=True)
    (Path(proj) / "brief.yaml").write_text(yaml.safe_dump(b, sort_keys=False))
    return b


def basic_project(proj, n_clips=4, clip_colours=None, aspect="16:9", ref_shot=1.25, bpm=120,
                  song_freq=440, music=True, logo=True, static=False, clip_tone=None, ref_audio=True,
                  ref_colours=("f0a040", "5a1808", "d06020", "300c04"), clip_dur=6.0, **brief):
    """Cool-coloured footage, warm reference, optional song, magenta logo, brief.yaml."""
    proj = Path(proj)
    colours = clip_colours or ["1e3a6e", "6aa0d0", "1a4a2a", "70b8a0", "2a2a50", "8090d0", "304060", "205070"]
    for i in range(n_clips):
        make_clip(proj / "footage" / f"clip{i + 1}.mp4", colours[i % len(colours)], dur=clip_dur,
                  moving=not static, tone=(clip_tone[i] if clip_tone else None))
    ref_wav = None
    if ref_audio:
        ref_wav = proj / ".refaudio.wav"
        make_song(ref_wav, bpm, ref_shot * 12, song_freq * 1.5)
    rw, rh = (360, 640) if aspect == "9:16" else (640, 360) if aspect == "16:9" else (400, 400)
    make_ref(proj / "refs" / "ref1.mp4", list(ref_colours), ref_shot, w=rw, h=rh, n_shots=12, audio=ref_wav)
    if ref_wav:
        ref_wav.unlink()
    if music:
        make_song(proj / "music" / "song.wav", bpm, 60, song_freq)
    if logo:
        make_logo(proj / "assets" / "logo.png")
    over = {"aspect": aspect}
    if not music:
        over["music"] = "none"
    if not logo:
        over["logo"] = ""
    over.update(brief)
    return write_brief(proj, **over)


def load(proj, name):
    sub = "out" if name == "report.json" else "work"
    return json.loads((Path(proj) / sub / name).read_text())


def save_plan(proj, plan):
    (Path(proj) / "work" / "plan.json").write_text(json.dumps(plan, indent=1))


# ---------------------------------------------------------------- audio measurement

def read_audio(path, sr=SR):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0


def read_audio_peak(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, "<f4")
    return float(np.max(np.abs(x))) if len(x) else 0.0


def seg(x, t0, t1, sr=SR):
    a, b = max(0, int(t0 * sr)), max(0, int(t1 * sr))
    return x[a:b]


def spectrum(x, sr=SR):
    if len(x) == 0:
        return np.zeros(1), np.zeros(1)
    w = np.hanning(len(x))
    s = np.abs(np.fft.rfft(x * w)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return f, s


def band_db(x, f0, bw=40, sr=SR):
    f, s = spectrum(x, sr)
    e = s[(f > f0 - bw) & (f < f0 + bw)].sum()
    return 10 * math.log10(e + 1e-12)


def outside_band_energy(x, lo, hi, sr=SR):
    f, s = spectrum(x, sr)
    return float(s[(f < lo) | (f > hi)].sum())


def dominant_freq(x, sr=SR, fmin=150):
    f, s = spectrum(x, sr)
    s = s.copy()
    s[f < fmin] = 0
    return float(f[int(np.argmax(s))])


def rms_db(x):
    if len(x) == 0:
        return -120.0
    return 20 * math.log10(math.sqrt(float(np.mean(x ** 2))) + 1e-9)


def near(t, grid, tol):
    return min(abs(t - g) for g in grid) <= tol
