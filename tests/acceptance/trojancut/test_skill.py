"""D5: AB10 (packaging both skills) and AB11 (SKILL.md flow, static)."""
import re
import zipfile
from pathlib import Path

import pytest

from _helpers import REPO, tc

SKILLS = REPO / "skills"


def frontmatter(text):
    assert text.startswith("---\n")
    front = text.split("---\n")[1]
    return dict((k.strip(), v.strip()) for k, v in (line.split(":", 1) for line in front.strip().splitlines() if ":" in line))


@pytest.fixture(scope="module")
def packaged(tmp_path_factory):
    out = tmp_path_factory.mktemp("pkg")
    tc("package", "--out", out)
    return out


def check_desc(fields, name):
    assert fields["name"] == name
    d = fields["description"]
    assert 0 < len(d) <= 1024 and "<" not in d and ">" not in d


def test_trojancut_zip(packaged):
    z = packaged / "trojancut.zip"
    assert z.exists() and z.stat().st_size <= 15 * 1024 * 1024
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert all(n.startswith("trojancut/") for n in names)
        assert "trojancut/SKILL.md" in names and "trojancut/scripts/tc.py" in names
        assert "trojancut/sfx/manifest.json" in names
        assert any(n.startswith("trojancut/engine/package") for n in names)
        assert not any("node_modules" in n or n.endswith(".pyc") or "__pycache__" in n for n in names)
        check_desc(frontmatter(zf.read("trojancut/SKILL.md").decode()), "trojancut")


def test_templatetrojancut_zip(packaged):
    z = packaged / "templatetrojancut.zip"
    assert z.exists() and z.stat().st_size <= 15 * 1024 * 1024
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert all(n.startswith("templatetrojancut/") for n in names)
        assert "templatetrojancut/SKILL.md" in names
        assert "templatetrojancut/scripts/make_template.py" in names
        assert "templatetrojancut/template/TrojanCut-Project/notes.txt" in names
        assert not any(n.lower().endswith(".zip") for n in names)  # claude.ai rejects nested zips
        assert not any("node_modules" in n or n.endswith(".pyc") for n in names)
        check_desc(frontmatter(zf.read("templatetrojancut/SKILL.md").decode()), "templatetrojancut")


def test_package_is_repeatable(packaged, tmp_path):
    tc("package", "--out", tmp_path)
    for name in ("trojancut.zip", "templatetrojancut.zip"):
        a = zipfile.ZipFile(packaged / name)
        b = zipfile.ZipFile(tmp_path / name)
        assert a.namelist() == b.namelist()
        for n in a.namelist():
            assert a.read(n) == b.read(n), n


# ---------------------------------------------------------------- AB11 (static)

@pytest.fixture(scope="module")
def skill_md():
    return (SKILLS / "trojancut" / "SKILL.md").read_text()


def test_skill_no_zip_hands_out_template(skill_md):
    low = skill_md.lower()
    assert "tc.py template" in skill_md or "trojancut-project.zip" in low
    # same six steps as /templatetrojancut
    for needle in ("extract all", "footage", "assets", "refs", "music", "notes.txt", "compress to zip file",
                   "send to", "500 mb", "/trojancut", "mp4"):
        assert needle in low, needle


def test_skill_with_zip_runs_pipeline_in_order(skill_md):
    order = ["open", "ingest", "analyze-refs", "autoplan", "validate", "render", "check"]
    pos = []
    for cmd in order:
        m = re.search(rf"tc\.py\"?\s+{re.escape(cmd)}\b", skill_md)
        assert m, f"SKILL.md never runs `tc.py {cmd}`"
        pos.append(m.start())
    assert pos == sorted(pos), dict(zip(order, pos))


def test_skill_paths_and_budget_rules(skill_md):
    low = skill_md.lower()
    assert "/mnt/user-data/uploads" in skill_md
    assert "/mnt/user-data/outputs" in skill_md
    assert "claude_images" in skill_md
    assert re.search(r"only.{0,80}claude_images|claude_images.{0,80}only", low, re.S)
    assert "plan.json" in skill_md and re.search(r"re-?run.{0,40}validate|validate.{0,60}again", low, re.S)
    assert re.search(r"(at most|only) one message", low)
    assert "claude code" in low
    assert re.search(r"local (folder|path)|folder or (a )?zip", low)
    assert "TROJANCUT_ENGINE" in skill_md or "engine" in low


def test_skill_scripts_present():
    scripts = SKILLS / "trojancut" / "scripts"
    assert (scripts / "tc.py").exists()
    assert (scripts / "requirements.txt").exists()
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text()
    assert "claude-video" in notices and "MIT" in notices
    assert "hyperframes" in notices.lower()
    readme = (REPO / "README.md").read_text().lower()
    for needle in ("customize", "skills", "code execution", "/templatetrojancut", "/trojancut",
                   "trojancut.zip", "templatetrojancut.zip"):
        assert needle in readme, needle
