"""Zip this skill's bundled template folder into TrojanCut-Project.zip. Standard library only, no network.

The folder ships unzipped because claude.ai rejects skill uploads that contain a nested zip.
Usage: python3 make_template.py [DEST_DIR]   (default: current folder)
"""
import sys
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SRC = SKILL / "template" / "TrojanCut-Project"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def main(dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "TrojanCut-Project.zip"
    names = (SKILL / "template" / "order.txt").read_text().split()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, (SRC / name).read_bytes())
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
