"""D8: AB15 (setup scripts install both skills; CLAUDE.md note)."""
import os
import subprocess
from pathlib import Path

import pytest

from _helpers import REPO

GUIDELINES_HEAD = "# CLAUDE.md\n\nBehavioral guidelines to reduce common LLM coding mistakes."
GUIDELINES_TAIL = ("**These guidelines are working if:** fewer unnecessary changes in diffs, \n"
                   "fewer rewrites due to overcomplication, and clarifying questions come \n"
                   "before implementation rather than after mistakes.")


def run_setup(home):
    env = dict(os.environ, HOME=str(home), TROJANCUT_HOME=str(home / ".cache" / "trojancut"))
    r = subprocess.run(["bash", str(REPO / "setup.sh")], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=30 * 60)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    return r


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(root).rglob("*")
            if p.is_file()}


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    run_setup(home)
    return home


def test_setup_sh_installs_both_skills(installed):
    skills = installed / ".claude" / "skills"
    assert (skills / "trojancut" / "SKILL.md").exists()
    assert (skills / "trojancut" / "scripts" / "tc.py").exists()
    assert (skills / "trojancut" / "sfx" / "manifest.json").exists()
    assert (skills / "templatetrojancut" / "SKILL.md").exists()
    assert (skills / "templatetrojancut" / "TrojanCut-Project.zip").exists()
    assert not any("node_modules" in str(p) or p.suffix == ".pyc" for p in skills.rglob("*"))


def test_second_run_changes_nothing(installed):
    skills = installed / ".claude" / "skills"
    before = snapshot(skills)
    run_setup(installed)
    assert snapshot(skills) == before


def test_replaces_older_copy(installed):
    skills = installed / ".claude" / "skills"
    (skills / "trojancut" / "SKILL.md").write_text("old")
    (skills / "trojancut" / "stale_file.txt").write_text("old")
    run_setup(installed)
    assert (skills / "trojancut" / "SKILL.md").read_text() == (REPO / "skills" / "trojancut" / "SKILL.md").read_text()
    assert not (skills / "trojancut" / "stale_file.txt").exists()


def test_setup_ps1_references_same_skills():
    ps = (REPO / "setup.ps1").read_text()
    low = ps.lower()
    assert "winget" in low
    for pkg in ("ffmpeg", "python.python.3.12", "openjs.nodejs"):
        assert pkg in low, pkg
    assert "$env:userprofile" in low and ".claude" in low and "skills" in low
    assert "install-skills" in ps or ("trojancut" in ps and "templatetrojancut" in ps)
    assert "tc.py" in ps and "setup" in ps


def test_claude_md_note_below_guidelines():
    text = (REPO / "CLAUDE.md").read_text()
    original = subprocess.run(["git", "show", "1e8774e:CLAUDE.md"], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.rstrip("\n")
    assert original.startswith(GUIDELINES_HEAD) and original.endswith(GUIDELINES_TAIL)
    assert text.startswith(original), "verbatim guidelines changed"
    note = text[len(original):].lower()
    assert note.strip(), "no project note below the guidelines"
    assert "set this up" in note or "set up" in note
    assert "setup.ps1" in note and "setup.sh" in note


def test_readme_claude_code_section():
    readme = (REPO / "README.md").read_text().lower()
    assert "set this up" in readme
    assert "restart" in readme
    assert "github.com/henrynorcutt/trojancut" in readme
