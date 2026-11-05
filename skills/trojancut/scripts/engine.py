"""Engine setup and detection: pinned Python deps, HyperFrames (Node) install, browser discovery.

`setup` installs once and stamps the result; later runs only re-check (fast). The ffmpeg engine
never needs any of this beyond numpy, Pillow, PyYAML and ffmpeg.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import SKILL_DIR, Fail, log, tc_home

HF_VERSION = "0.9.16"
ENGINE_SRC = SKILL_DIR / "engine"
REQUIREMENTS = SKILL_DIR / "scripts" / "requirements.txt"


def hf_env(browser=None):
    env = dict(os.environ, DO_NOT_TRACK="1", HYPERFRAMES_NO_UPDATE_CHECK="1", HYPERFRAMES_SKIP_SKILLS="1")
    if browser:
        env["HYPERFRAMES_BROWSER_PATH"] = str(browser)
    return env


# ---------------------------------------------------------------- browser discovery

def _windows_browser_paths():
    roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    rels = [r"Google\Chrome\Application\chrome.exe", r"Chromium\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"]
    return [Path(r) / p for r in roots if r for p in rels]


MAC_BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
PATH_BROWSERS = ["chrome-headless-shell", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "msedge", "microsoft-edge", "microsoft-edge-stable"]


def find_browser():
    """A Chrome-family browser HyperFrames can drive, or None.

    TROJANCUT_BROWSER (or HYPERFRAMES_BROWSER_PATH) set to a path that does not exist means
    "no usable browser here" and is respected, so the ffmpeg engine is chosen.
    """
    for var in ("TROJANCUT_BROWSER", "HYPERFRAMES_BROWSER_PATH"):
        v = os.environ.get(var)
        if v:
            return Path(v) if Path(v).is_file() else None
    for name in PATH_BROWSERS:
        p = shutil.which(name)
        if p:
            return Path(p)
    cands = _windows_browser_paths() if os.name == "nt" else [Path(p) for p in MAC_BROWSERS]
    for p in cands:
        if p.is_file():
            return p
    # A browser HyperFrames downloaded itself (puppeteer cache), when the network allowed it.
    cache = Path.home() / ".cache" / "puppeteer"
    for pattern in ("chrome-headless-shell/*/*/chrome-headless-shell*", "chrome/*/*/chrome", "chrome/*/*/chrome.exe"):
        for p in sorted(cache.glob(pattern)):
            if p.is_file() and os.access(p, os.X_OK):
                return p
    return None


# ---------------------------------------------------------------- node + hyperframes

def node_tools():
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        return None, None, "Node.js/npm not found"
    try:
        v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        major = int(v.lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None, "Node.js did not report a version"
    if major < 22:
        return None, None, f"Node.js {v} is too old (HyperFrames needs 22+)"
    return node, npm, v


def engine_dir():
    return tc_home() / f"engine-{HF_VERSION}"


def lock_hash():
    h = hashlib.sha256()
    for f in ("package.json", "package-lock.json"):
        h.update((ENGINE_SRC / f).read_bytes())
    return h.hexdigest()[:16]


def hf_cli():
    p = engine_dir() / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    return p if p.is_file() else None


def installed_version():
    p = engine_dir() / "node_modules" / "hyperframes" / "package.json"
    try:
        return json.loads(p.read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def gsap_path():
    root = engine_dir() / "node_modules" / "hyperframes" / "dist" / "vendor" / "npm"
    hits = sorted(root.glob("gsap@*/dist/gsap.min.js"))
    return hits[-1] if hits else None


STAMP = "setup-stamp.json"


def read_stamp():
    try:
        return json.loads((engine_dir() / STAMP).read_text())
    except (OSError, ValueError):
        return {}


def hyperframes_status():
    """(usable, reason, browser, node) without installing anything."""
    node, npm, nv = node_tools()
    if not node:
        return False, nv, None, None
    if installed_version() != HF_VERSION or not hf_cli():
        return False, f"HyperFrames {HF_VERSION} is not installed (run `tc.py setup`)", None, node
    browser = find_browser()
    if not browser:
        return False, "no Chrome/Chromium/Edge browser found for HyperFrames", None, node
    st = read_stamp()
    if st.get("lock") == lock_hash() and st.get("smoke", {}).get(str(browser)) is False:
        return False, f"HyperFrames could not render with {browser} during setup", browser, node
    return True, "", browser, node


def install_hyperframes(npm):
    d = engine_dir()
    d.mkdir(parents=True, exist_ok=True)
    st = read_stamp()
    if st.get("lock") == lock_hash() and installed_version() == HF_VERSION:
        return True, "already installed"
    for f in ("package.json", "package-lock.json"):
        shutil.copyfile(ENGINE_SRC / f, d / f)
    log(f"installing hyperframes@{HF_VERSION} into {d} (one time) ...")
    try:
        r = subprocess.run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--loglevel=error"],
                           cwd=d, capture_output=True, text=True, timeout=20 * 60, env=hf_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"npm ci failed: {e}"
    if r.returncode != 0 or installed_version() != HF_VERSION:
        tail = (r.stderr or r.stdout).strip().splitlines()
        return False, f"npm ci failed: {tail[-1] if tail else 'exit ' + str(r.returncode)}"
    (d / STAMP).write_text(json.dumps({"lock": lock_hash(), "smoke": {}}))
    return True, "installed"


SMOKE_HTML = """<!doctype html><html><head><meta charset="UTF-8"><script src="gsap.min.js"></script>
<style>html,body{margin:0;width:64px;height:64px;overflow:hidden;background:transparent}
#root{position:relative;width:64px;height:64px}#b{position:absolute;left:8px;top:8px;width:20px;height:20px;background:#f0f}</style>
</head><body><div id="root" data-composition-id="main" data-start="0" data-duration="0.2" data-width="64" data-height="64">
<div id="b" class="clip" data-start="0" data-duration="0.2"></div></div>
<script>window.__timelines=window.__timelines||{};const tl=gsap.timeline({paused:true});
tl.fromTo("#b",{x:0},{x:20,duration:0.2},0);window.__timelines["main"]=tl;</script></body></html>"""


def smoke_render(node, browser):
    d = engine_dir() / "smoke"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "index.html").write_text(SMOKE_HTML)
    shutil.copyfile(gsap_path(), d / "gsap.min.js")
    try:
        r = subprocess.run([node, str(hf_cli()), "render", ".", "--format", "png-sequence", "-o", str(d / "frames"),
                            "--fps", "10", "--quiet"], cwd=d, capture_output=True, text=True, timeout=600,
                           env=hf_env(browser))
    except (OSError, subprocess.TimeoutExpired) as e:
        (d / "smoke.log").write_text(f"{type(e).__name__}: {e}")
        return False
    (d / "smoke.log").write_text(f"exit {r.returncode}\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}")
    return r.returncode == 0 and any((d / "frames").glob("*.png"))


def python_deps():
    missing = []
    for mod in ("numpy", "PIL", "yaml"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return True, "ok"
    log(f"installing Python packages ({', '.join(missing)}) ...")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(cmd + ["--user"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, "pip could not install " + ", ".join(missing)
    return True, "installed"


def setup():
    ok, msg = python_deps()
    if not ok:
        raise Fail(f"{msg}; install them with: python -m pip install -r {REQUIREMENTS}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise Fail("ffmpeg/ffprobe not found on PATH; install ffmpeg first")
    print(f"python deps: {msg}")
    print("ffmpeg: ok")
    node, npm, nv = node_tools()
    if not node:
        print(f"hyperframes: unavailable ({nv})")
        print("engine: ffmpeg")
        return
    ok, msg = install_hyperframes(npm)
    if not ok:
        print(f"hyperframes: unavailable ({msg})")
        print("engine: ffmpeg")
        return
    browser = find_browser()
    if not browser:
        print("hyperframes: installed, but no Chrome/Chromium/Edge browser was found")
        print("engine: ffmpeg")
        return
    st = read_stamp()
    smoke = st.setdefault("smoke", {})
    if smoke.get(str(browser)) is not True:  # never tested, or failed before: (re)try
        smoke[str(browser)] = smoke_render(node, browser)
        st["lock"] = lock_hash()
        (engine_dir() / STAMP).write_text(json.dumps(st))
    if not smoke[str(browser)]:
        print(f"hyperframes: test render failed with {browser}")
        print("engine: ffmpeg")
        return
    print(f"hyperframes: {HF_VERSION} ({msg}), node {nv}, browser {browser}")
    print("engine: hyperframes")


def choose_engine():
    """('hyperframes'|'ffmpeg', fallback_reason) from TROJANCUT_ENGINE and what is usable."""
    want = os.environ.get("TROJANCUT_ENGINE", "auto").strip().lower() or "auto"
    if want not in ("auto", "ffmpeg", "hyperframes"):
        raise Fail(f"TROJANCUT_ENGINE must be auto or ffmpeg, got {want!r}")
    if want == "ffmpeg":
        return "ffmpeg", "forced by TROJANCUT_ENGINE=ffmpeg"
    ok, reason, _, _ = hyperframes_status()
    if ok:
        return "hyperframes", ""
    if want == "hyperframes":
        raise Fail(f"TROJANCUT_ENGINE=hyperframes but {reason}")
    return "ffmpeg", reason
