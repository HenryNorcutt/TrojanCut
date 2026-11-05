#!/usr/bin/env python3
"""TrojanCut CLI. Every command exits 0 on success, or 1 with a one-line reason.

  setup                         install pinned deps; print which engine is usable
  open ZIP_OR_DIR... P          unpack project zip(s) / folder into P, write P/brief.yaml from notes.txt
  ingest P                      extract zips, index media, contact sheets -> work/index.json
  analyze-refs P                reference cuts, tempo, beats, colour, LUT, frames -> work/style.json
  autoplan P                    heuristic edit plan -> work/plan.json
  validate P                    check work/plan.json
  render P                      render out/final.mp4 (TROJANCUT_ENGINE=auto|ffmpeg)
  check P                       measure out/final.mp4 -> out/report.json
  template --out D              write D/TrojanCut-Project.zip
  package --out D               write D/trojancut.zip and D/templatetrojancut.zip
  install-skills --dest D       copy both skills into D (e.g. ~/.claude/skills), replacing old copies
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True

from common import Fail  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tc.py", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    o = sub.add_parser("open")
    o.add_argument("paths", nargs="+", help="project zip(s) or folder(s), then the project dir")
    for name in ("ingest", "analyze-refs", "autoplan", "validate", "render", "check"):
        sub.add_parser(name).add_argument("project")
    for name in ("template", "package"):
        sub.add_parser(name).add_argument("--out", required=True)
    sub.add_parser("install-skills").add_argument("--dest", required=True)

    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        if args.cmd == "setup":
            import engine
            engine.setup()
        elif args.cmd == "open":
            if len(args.paths) < 2:
                raise Fail("usage: tc.py open ZIP [ZIP...] PROJECT_DIR")
            import project
            project.open_project([Path(p) for p in args.paths[:-1]], Path(args.paths[-1]))
        elif args.cmd == "ingest":
            import ingest
            ingest.ingest(args.project)
        elif args.cmd == "analyze-refs":
            import analyze
            analyze.analyze_refs(args.project)
        elif args.cmd == "autoplan":
            import planner
            planner.autoplan(args.project)
        elif args.cmd == "validate":
            import validate
            validate.validate_cmd(args.project)
        elif args.cmd == "render":
            import render
            render.render(args.project)
        elif args.cmd == "check":
            import check
            return check.check(args.project)
        elif args.cmd == "template":
            import project
            project.write_template(Path(args.out))
        elif args.cmd == "package":
            import package
            package.package(Path(args.out))
        elif args.cmd == "install-skills":
            import package
            package.install_skills(Path(args.dest))
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except Exception as e:  # last resort: never show a traceback to the user
        import os
        import traceback
        if os.environ.get("TROJANCUT_DEBUG"):
            traceback.print_exc()
        where = traceback.extract_tb(e.__traceback__)[-1]
        print(f"error: unexpected {type(e).__name__} in {Path(where.filename).name}:{where.lineno}: {e}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
