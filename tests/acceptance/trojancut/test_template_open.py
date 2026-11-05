"""D7: AB12 (template), AB13 (open), AB14 (/templatetrojancut)."""
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml

from _helpers import (REPO, engine_env, load, make_clip, make_logo, make_ref, make_song, run_pipeline, tc, vstream,
                      write_wav)

QUESTIONS = [
    ("Shortest length in seconds", "15"),
    ("Longest length in seconds", "30"),
    ("Shape (vertical / horizontal / square)", "vertical"),
    ("Music (none / reference audio / my songs)", "my songs"),
    ("Song order (file names separated by ;  blank = alphabetical)", ""),
    ("Song parts (e.g. song1.mp3 0:45-1:15; song2.mp3 auto  blank = Claude picks)", ""),
    ("Switch between songs (cut / quick fade / Claude decides)", "Claude decides"),
    ("Keep sound from the clips (yes / no)", "no"),
    ("Sound effects (none / some / lots)", "some"),
    ("Which sound effects (built-in / mine / both)", "both"),
    ("Copy from the references (cuts / color / text / everything)", "everything"),
    ("Effects amount (low / medium / high)", "medium"),
    ("Logo file (name in assets folder)", ""),
    ("Logo corner (top-left / top-right / bottom-left / bottom-right / none)", "top-right"),
    ("Title text at the start (blank = none)", ""),
    ("Must include", ""),
    ("Avoid", ""),
    ("Anything else (any notes or context, as many lines as you like below this one)", ""),
]
FOLDERS = ["footage", "assets", "refs", "music", "sfx"]


def squash(s):
    return re.sub(r"\s+", " ", s).strip()


def split_qa(line):
    """Split 'Question (may hold 0:45): answer' at the first colon outside parentheses."""
    depth = 0
    for i, ch in enumerate(line):
        depth += ch == "("
        depth -= ch == ")"
        if ch == ":" and depth == 0:
            return line[:i], line[i + 1:]
    raise AssertionError(f"no question/answer colon in {line!r}")


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    out = tmp_path_factory.mktemp("tpl")
    tc("template", "--out", out)
    z = out / "TrojanCut-Project.zip"
    assert z.exists()
    return z


# ---------------------------------------------------------------- AB12

def test_template_layout(template):
    with zipfile.ZipFile(template) as zf:
        names = zf.namelist()
        for f in FOLDERS:
            assert f"{f}/README.txt" in names, names
            text = zf.read(f"{f}/README.txt").decode().strip()
            assert text and len(text.splitlines()) == 1, (f, text)
        sfx_readme = zf.read("sfx/README.txt").decode().lower()
        assert "whoosh" in sfx_readme and "name" in sfx_readme
        how = zf.read("HOW-TO.txt").decode()
        steps = re.findall(r"(?m)^\s*([1-9])[.)]", how)
        assert steps[:5] == ["1", "2", "3", "4", "5"], steps
        assert "500 MB" in how and re.search(r"several zips|more than one zip|multiple zips", how, re.I)
        notes = zf.read("notes.txt").decode().replace("\r\n", "\n")
    lines = [l for l in notes.split("\n") if l.strip()]
    assert len(lines) == len(QUESTIONS), lines
    for line, (q, default) in zip(lines, QUESTIONS):
        qq, aa = split_qa(line)
        assert squash(qq) == squash(q), (qq, q)
        assert aa.strip() == default, (q, aa)


def test_template_is_deterministic(template, tmp_path):
    tc("template", "--out", tmp_path)
    assert (tmp_path / "TrojanCut-Project.zip").read_bytes() == template.read_bytes()


# ---------------------------------------------------------------- helpers for AB13

def unpack(template, dest):
    with zipfile.ZipFile(template) as zf:
        zf.extractall(dest)
    return dest


def set_answers(folder, **answers):
    """answers keyed by question prefix (case-insensitive)."""
    p = Path(folder) / "notes.txt"
    lines = p.read_text().replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        if ":" in line:
            q, _ = split_qa(line)
            for k, v in answers.items():
                if squash(q).lower().startswith(k.lower()):
                    line = f"{q}: {v}"
            out.append(line)
        else:
            out.append(line)
    p.write_text("\r\n".join(out))


def zip_folder(folder, dest, wrapper=None, junk=False):
    folder = Path(folder)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                rel = f.relative_to(folder).as_posix()
                zf.write(f, f"{wrapper}/{rel}" if wrapper else rel)
        if junk:
            zf.writestr("__MACOSX/._notes.txt", b"junk")
            zf.writestr((f"{wrapper}/" if wrapper else "") + ".DS_Store", b"junk")
            zf.writestr((f"{wrapper}/" if wrapper else "") + "footage/._clip1.mp4", b"junk")
    return dest


def brief(proj):
    return yaml.safe_load((Path(proj) / "brief.yaml").read_text())


def filled(template, root, n_clips=3, songs=("track.wav",), logo=True):
    f = unpack(template, Path(root) / "TrojanCut-Project")
    for i in range(n_clips):
        make_clip(f / "footage" / f"clip{i + 1}.mp4", ["1e3a6e", "6aa0d0", "1a4a2a", "70b8a0"][i % 4], dur=5,
                  moving=False)
    make_ref(f / "refs" / "style.mp4", ["f0a040", "5a1808"], 1.0, w=360, h=640, n_shots=8)
    for k, s in enumerate(songs):
        make_song(f / "music" / s, 100 + 20 * k, 90, 300 + 100 * k)
    if logo:
        make_logo(f / "assets" / "brand.png")
    return f


# ---------------------------------------------------------------- AB13

def test_round_trip_wrapper_folder_renders(template, tmp_path):
    f = filled(template, tmp_path / "a")
    set_answers(f, **{"Shortest": "8", "Longest": "12", "Title text": "  Big Day ", "Sound effects": "none"})
    z = zip_folder(f, tmp_path / "send.zip", wrapper="TrojanCut-Project", junk=True)
    proj = tmp_path / "proj"
    tc("open", z, proj)
    b = brief(proj)
    assert b["min_seconds"] == 8 and b["max_seconds"] == 12
    assert b["aspect"] == "9:16" and b["match"] == "full" and b["effects_intensity"] == "medium"
    assert b["music"] == "music/track.wav"
    assert b["logo"] == "assets/brand.png" and b["logo_position"] == "top-right"
    assert b["title_text"] == "Big Day"
    assert not any(p.name.startswith("._") or p.name == ".DS_Store" for p in proj.rglob("*"))
    assert not (proj / "__MACOSX").exists()
    run_pipeline(proj, env=engine_env("ffmpeg"))
    rep = load(proj, "report.json")
    assert rep["ok"] is True
    v = vstream(proj / "out" / "final.mp4")
    assert (v["width"], v["height"]) == (1080, 1920)


def test_root_zip_and_merge_two_zips(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=4)
    second = tmp_path / "b" / "TrojanCut-Project"
    (second / "footage").mkdir(parents=True)
    for name in ("clip3.mp4", "clip4.mp4"):
        shutil.move(f / "footage" / name, second / "footage" / name)
    set_answers(f, **{"Shape": " SQUARE ", "Copy from": "Color", "Effects amount": "HIGH"})
    z1 = zip_folder(f, tmp_path / "one.zip")
    z2 = zip_folder(second, tmp_path / "two.zip", wrapper="TrojanCut-Project (2)")
    proj = tmp_path / "proj"
    tc("open", z1, z2, proj)
    clips = sorted(p.name for p in (proj / "footage").glob("*.mp4"))
    assert clips == ["clip1.mp4", "clip2.mp4", "clip3.mp4", "clip4.mp4"]
    b = brief(proj)
    assert b["aspect"] == "1:1" and b["match"] == "color" and b["effects_intensity"] == "high"


@pytest.mark.parametrize("shape,aspect", [("horizontal", "16:9"), ("Vertical", "9:16"), ("square", "1:1"),
                                          ("", "9:16")])
def test_shape_mapping(template, tmp_path, shape, aspect):
    f = filled(template, tmp_path / "a", n_clips=1)
    set_answers(f, Shape=shape)
    proj = tmp_path / "p"
    tc("open", zip_folder(f, tmp_path / "s.zip"), proj)
    assert brief(proj)["aspect"] == aspect


def test_music_lines_mapping(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1, songs=("alpha.wav", "beta.mp3.wav", "gamma.wav"))
    set_answers(f, **{"Song order": "gamma.wav; alpha.wav;beta.mp3.wav",
                      "Song parts": "gamma.wav 0:45-1:15; alpha.wav auto; beta.mp3.wav 12-20.5",
                      "Switch between": "quick fade", "Keep sound": "YES"})
    proj = tmp_path / "p"
    tc("open", zip_folder(f, tmp_path / "m.zip"), proj)
    b = brief(proj)
    assert [m["file"] for m in b["music"]] == ["music/gamma.wav", "music/alpha.wav", "music/beta.mp3.wav"]
    assert b["music"][0]["part"] == [45, 75]
    assert b["music"][1]["part"] == "auto"
    assert b["music"][2]["part"] == [12, 20.5]
    assert b["song_switch"] == "fade" and b["keep_clip_audio"] is True


def test_music_none_reference_and_errors(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1, songs=())
    set_answers(f, Music="None")
    proj = tmp_path / "p1"
    tc("open", zip_folder(f, tmp_path / "n.zip"), proj)
    assert brief(proj)["music"] == "none"
    set_answers(f, Music="reference audio")
    proj = tmp_path / "p2"
    tc("open", zip_folder(f, tmp_path / "r.zip"), proj)
    assert brief(proj)["music"] == "reference"
    set_answers(f, Music="my songs")
    r = tc("open", zip_folder(f, tmp_path / "e.zip"), tmp_path / "p3", ok=False)
    assert "music" in (r.stdout + r.stderr).lower()


def test_sfx_lines_mapping(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1)
    set_answers(f, **{"Sound effects": "LOTS", "Which sound": "mine"})
    proj = tmp_path / "p1"
    r = tc("open", zip_folder(f, tmp_path / "x.zip"), proj)
    b = brief(proj)
    assert b["sfx_amount"] == "lots" and b["sfx_source"] == "built-in"
    assert "built-in" in (r.stdout + r.stderr).lower()
    write_wav(f / "sfx" / "whoosh_big.wav", np.random.default_rng(1).normal(0, 0.2, 22050))
    proj = tmp_path / "p2"
    tc("open", zip_folder(f, tmp_path / "y.zip"), proj)
    assert brief(proj)["sfx_source"] == "mine"
    # no sfx folder at all is fine
    shutil.rmtree(f / "sfx")
    proj = tmp_path / "p3"
    tc("open", zip_folder(f, tmp_path / "z.zip"), proj)
    assert brief(proj)["sfx_source"] == "built-in"


def test_open_errors(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1)
    set_answers(f, Shortest="40", Longest="20")
    r = tc("open", zip_folder(f, tmp_path / "1.zip"), tmp_path / "p1", ok=False)
    assert "shortest" in (r.stdout + r.stderr).lower()
    set_answers(f, Shortest="ten", Longest="20")
    r = tc("open", zip_folder(f, tmp_path / "2.zip"), tmp_path / "p2", ok=False)
    assert "shortest" in (r.stdout + r.stderr).lower()
    set_answers(f, Shortest="10", **{"Logo file": "missing.png"})
    r = tc("open", zip_folder(f, tmp_path / "3.zip"), tmp_path / "p3", ok=False)
    assert "missing.png" in (r.stdout + r.stderr)
    set_answers(f, **{"Logo file": "", "Effects amount": "extreme"})
    r = tc("open", zip_folder(f, tmp_path / "4.zip"), tmp_path / "p4", ok=False)
    assert "effects" in (r.stdout + r.stderr).lower()


def test_logo_autofill_only_when_single(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1, logo=False)
    make_logo(f / "assets" / "one.png")
    make_logo(f / "assets" / "two.png", rgb=(0, 0, 255))
    proj = tmp_path / "p"
    tc("open", zip_folder(f, tmp_path / "l.zip"), proj)
    assert not brief(proj).get("logo")


def test_free_text_notes_kept_verbatim(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1)
    set_answers(f, **{"Title text": "Hi"})
    free = ("Make it punchy: fast cuts at the start.\n"
            "Shape (vertical / horizontal / square): horizontal\n"
            "Shortest length in seconds: 99\n"
            "\n"
            "  keep the beach shot near the end  ")
    p = f / "notes.txt"
    p.write_text(p.read_text().rstrip("\r\n") + "\r\n" + free.replace("\n", "\r\n") + "\r\n")
    proj = tmp_path / "p"
    tc("open", zip_folder(f, tmp_path / "n.zip"), proj)
    b = brief(proj)
    assert b["notes"].strip("\n") == free
    assert b["aspect"] == "9:16" and b["min_seconds"] == 15, "free text was parsed as answers"
    assert b["title_text"] == "Hi"


def test_free_text_on_the_same_line(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1)
    p = f / "notes.txt"
    lines = p.read_text().replace("\r\n", "\n").rstrip("\n").split("\n")
    lines[-1] = lines[-1] + " slow mo on the jump: please\nand more: here"
    p.write_text("\n".join(lines) + "\n")
    proj = tmp_path / "p"
    tc("open", zip_folder(f, tmp_path / "s.zip"), proj)
    assert brief(proj)["notes"].strip() == "slow mo on the jump: please\nand more: here"


def test_older_wording_still_parses(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1)
    old = ("shortest length in seconds:   12\n"
           "LONGEST LENGTH:20\n"
           "Shape (vertical / horizontal):  square\n"
           "Music file (name in music folder, or \"reference audio\"): track.wav\n"
           "Copy from the references: cuts\n"
           "Effects amount: low\n"
           "Logo file: brand.png\n"
           "Logo corner: bottom-left\n"
           "Title text at the start: Old Style\n"
           "Must include: the dog\n"
           "Avoid:\n"
           "Anything else: just this line\n")
    (f / "notes.txt").write_text(old)
    proj = tmp_path / "p"
    tc("open", zip_folder(f, tmp_path / "o.zip"), proj)
    b = brief(proj)
    assert b["min_seconds"] == 12 and b["max_seconds"] == 20 and b["aspect"] == "1:1"
    assert b["match"] == "cuts" and b["effects_intensity"] == "low"
    assert b["logo"] == "assets/brand.png" and b["logo_position"] == "bottom-left"
    assert b["title_text"] == "Old Style" and b["notes"].strip() == "just this line"
    assert b["music"] == "music/track.wav"
    assert "the dog" in str(b["must_include"])


def test_skill_md_treats_notes_as_instructions():
    md = (REPO / "skills" / "trojancut" / "SKILL.md").read_text().lower()
    assert "notes" in md and "override" in md
    assert re.search(r"not.{0,60}(answered|answers)|(answered|answers).{0,80}win", md, re.S)


def test_missing_notes_uses_defaults(template, tmp_path):
    f = filled(template, tmp_path / "a", n_clips=1)
    (f / "notes.txt").unlink()
    proj = tmp_path / "p"
    r = tc("open", zip_folder(f, tmp_path / "nn.zip"), proj)
    assert "notes.txt" in (r.stdout + r.stderr)
    b = brief(proj)
    assert b["min_seconds"] == 15 and b["max_seconds"] == 30 and b["aspect"] == "9:16"


# ---------------------------------------------------------------- AB14

def test_templatetrojancut_skill(tmp_path, template):
    md = (REPO / "skills" / "templatetrojancut" / "SKILL.md").read_text()
    keys = {l.split(":", 1)[0].strip() for l in md.split("---\n")[1].strip().splitlines() if ":" in l and not l.startswith(" ")}
    assert keys <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}, keys
    low = md.lower()
    assert "/mnt/user-data/outputs" in md and "TrojanCut-Project.zip" in md
    steps = re.findall(r"(?m)^\s*([1-6])\.\s", md)
    assert [s for s in steps if s in "123456"][:6] == list("123456"), steps
    for needle in ("extract all", "footage", "assets", "refs", "music", "notes.txt", "blank",
                   "compress to zip file", "send to", "compressed (zipped) folder", "500 mb",
                   "/trojancut", "download the mp4"):
        assert needle in low, needle
    for bad in ("pip install", "npm ", "curl ", "http://", "https://"):
        assert bad not in low, bad
    tc("package", "--out", tmp_path)
    with zipfile.ZipFile(tmp_path / "templatetrojancut.zip") as zf:
        bundled = zf.read("templatetrojancut/TrojanCut-Project.zip")
    assert bundled == template.read_bytes()
