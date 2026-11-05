"""Synthetic TrojanCut project for the end-to-end check. Written by the coordinator; protected.

Usage: python3 tests/e2e/make_fixtures.py <project_dir>

Creates:
  footage/clip1..4.mp4 + footage/more.zip (clip5, clip6)  16:9, cool colours, moving box
  assets/logo.png        solid magenta 256x256
  refs/ref1.mp4          9:16, 12 s, warm colours, a hard cut every 1.0 s, 120 BPM clicks
  music/track.wav        45 s, 120 BPM clicks
  brief.yaml
"""
import subprocess
import sys
import zipfile
from pathlib import Path

CLIP_COLOURS = ["1e3a6e", "6aa0d0", "1a4a2a", "70b8a0", "2a2a50", "8090d0"]
REF_COLOURS = ["f0a040", "5a1808", "d06020", "300c04"]
CLICKS = "0.6*sin(2*PI*880*t)*exp(-40*mod(t\\,0.5))+0.1*sin(2*PI*110*t)"

BRIEF = """\
min_seconds: 15
max_seconds: 30
aspect: "9:16"
resolution: 1080
fps: 30
music: music/track.wav
match: full
logo: assets/logo.png
logo_position: top-right
title_text: "TROJAN TEST"
captions: false
effects_intensity: low
must_include: []
avoid: []
notes: ""
"""


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def main(root: Path):
    for d in ("footage", "assets", "refs", "music", "tmp"):
        (root / d).mkdir(parents=True, exist_ok=True)

    for i, c in enumerate(CLIP_COLOURS, 1):
        out = root / "footage" / f"clip{i}.mp4"
        video = ["-f", "lavfi", "-i", f"color=c=0x{c}:s=1920x1080:r=30:d=8"]
        vf = "drawbox=x='mod(t*240\\,1700)':y=400:w=200:h=200:color=white:t=fill"
        if i <= 3:
            ff(*video, "-f", "lavfi", "-i", "anoisesrc=a=0.02:d=8",
               "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out))
        else:
            ff(*video, "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out))

    with zipfile.ZipFile(root / "footage" / "more.zip", "w") as z:
        for i in (5, 6):
            p = root / "footage" / f"clip{i}.mp4"
            z.write(p, p.name)
            p.unlink()

    ff("-f", "lavfi", "-i", "color=c=0xff00ff:s=256x256:d=1", "-frames:v", "1", str(root / "assets" / "logo.png"))
    ff("-f", "lavfi", "-i", f"aevalsrc='{CLICKS}':s=44100:d=45", str(root / "music" / "track.wav"))

    segs = []
    for k in range(12):
        seg = root / "tmp" / f"seg{k:02d}.mp4"
        c = REF_COLOURS[k % len(REF_COLOURS)]
        ff("-f", "lavfi", "-i", f"color=c=0x{c}:s=1080x1920:r=30:d=1",
           "-vf", "drawbox=x='mod(t*300\\,800)':y=900:w=150:h=150:color=white:t=fill",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg))
        segs.append(seg)
    lst = root / "tmp" / "list.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-f", "lavfi", "-i", f"aevalsrc='{CLICKS}':s=44100:d=12",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(root / "refs" / "ref1.mp4"))
    for s in segs:
        s.unlink()
    lst.unlink()
    (root / "tmp").rmdir()

    (root / "brief.yaml").write_text(BRIEF)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
