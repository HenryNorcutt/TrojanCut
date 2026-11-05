"""`package --out D` (both skill ZIPs) and `install-skills --dest D` (copy both skills into a skills folder)."""
import filecmp
import shutil
import zipfile
from pathlib import Path

from common import SKILL_DIR
from project import ZIP_NAME, template_bytes

SKILLS_ROOT = SKILL_DIR.parent
TEMPLATE_SKILL = SKILLS_ROOT / "templatetrojancut"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache"}


def skill_files(root):
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_dir() or any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if p.suffix in (".pyc", ".pyo"):
            continue
        out.append((p, rel.as_posix()))
    return out


def write_zip(dest, top, files, extra=()):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        entries = [(f"{top}/{rel}", p.read_bytes()) for p, rel in files] + [(f"{top}/{n}", b) for n, b in extra]
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith((".py", ".sh")) else 0o644) << 16
            zf.writestr(info, data)


def package(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_zip(out / "trojancut.zip", "trojancut", skill_files(SKILL_DIR))
    write_zip(out / "templatetrojancut.zip", "templatetrojancut",
              [f for f in skill_files(TEMPLATE_SKILL) if f[1] != ZIP_NAME], extra=[(ZIP_NAME, template_bytes())])
    for z in ("trojancut.zip", "templatetrojancut.zip"):
        size = (out / z).stat().st_size
        if size > 15 * 1024 * 1024:
            raise SystemExit(f"{z} is {size / 1e6:.1f} MB, over the 15 MB limit")
        print(f"wrote {out / z} ({size / 1e6:.2f} MB)")


def sync_tree(files, dest, extra=()):
    """Make dest contain exactly `files` (+ extra bytes); untouched when already identical."""
    want = {rel: p for p, rel in files}
    want_bytes = dict(extra)
    changed = False
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(dest.rglob("*"), reverse=True):
        rel = p.relative_to(dest).as_posix()
        if p.is_file() and rel not in want and rel not in want_bytes:
            p.unlink()
            changed = True
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
            changed = True
    for rel, src in want.items():
        t = dest / rel
        if t.is_file() and filecmp.cmp(src, t, shallow=False):
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, t)
        changed = True
    for rel, data in want_bytes.items():
        t = dest / rel
        if t.is_file() and t.read_bytes() == data:
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(data)
        changed = True
    return changed


def install_skills(dest):
    dest = Path(dest).expanduser()
    a = sync_tree(skill_files(SKILL_DIR), dest / "trojancut")
    b = sync_tree([f for f in skill_files(TEMPLATE_SKILL) if f[1] != ZIP_NAME], dest / "templatetrojancut",
                  extra=[(ZIP_NAME, template_bytes())])
    state = "updated" if (a or b) else "already up to date"
    print(f"skills trojancut and templatetrojancut {state} in {dest}")
