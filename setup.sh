#!/usr/bin/env bash
# TrojanCut setup for macOS / Linux: installs ffmpeg, Python and Node when missing, runs
# `tc.py setup`, and installs both skills into ~/.claude/skills. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")"

need() { ! command -v "$1" >/dev/null 2>&1; }
install_pkg() {
  if command -v brew >/dev/null 2>&1; then brew install "$@"
  elif command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then apt-get install -y "$@"; else sudo apt-get install -y "$@"; fi
  else echo "Please install: $*" >&2; return 1; fi
}

if need ffmpeg || need ffprobe; then echo "Installing ffmpeg ..."; install_pkg ffmpeg; fi
if need python3; then echo "Installing Python ..."; install_pkg python3; fi
if need node; then
  echo "Installing Node.js (optional, enables the HyperFrames engine) ..."
  if command -v brew >/dev/null 2>&1; then brew install node@22 || true; else install_pkg nodejs npm || true; fi
fi

python3 skills/trojancut/scripts/tc.py setup
python3 skills/trojancut/scripts/tc.py install-skills --dest "$HOME/.claude/skills"
echo "Done. Restart Claude Code, then use /templatetrojancut and /trojancut."
