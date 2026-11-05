"""HyperFrames overlay: animated title card, animated logo and transition accents as a transparent PNG
sequence (HTML + GSAP rendered by hyperframes@0.9.16), composited over the ffmpeg base by render.py."""
import html
import json
import shutil
import subprocess
from pathlib import Path

import engine as eng
from common import Fail, log

POS_CSS = {"top-left": "left:{m}px;top:{m}px", "top-right": "right:{m}px;top:{m}px",
           "bottom-left": "left:{m}px;bottom:{m}px", "bottom-right": "right:{m}px;bottom:{m}px"}


def composition(plan, logo_name):
    W, H, D = plan["width"], plan["height"], plan["duration"]
    els, tl = [], []
    css = [f"*{{margin:0;padding:0;box-sizing:border-box}}",
           f"html,body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent}}",
           f"#root{{position:relative;width:{W}px;height:{H}px;font-family:'Arial Black',Arial,Helvetica,sans-serif}}"]
    if plan.get("logo"):
        lg = plan["logo"]
        size = int(round(min(W, H) * lg.get("size", 0.14)))
        m = int(round(min(W, H) * 0.04))
        pos = POS_CSS.get(lg["position"], POS_CSS["top-right"]).format(m=m)
        css.append(f"#logo{{position:absolute;{pos};width:{size}px;height:{size}px;object-fit:contain;"
                   "transform-origin:50% 50%}")
        els.append(f'<img id="logo" class="clip" src="{logo_name}" data-start="0" data-duration="{D:.3f}">')
        tl.append('tl.fromTo("#logo",{scale:0.2,opacity:0,rotation:-25},'
                  '{scale:1,opacity:1,rotation:0,duration:0.45,ease:"back.out(2.2)"},0);')
        # gentle pulse on every 4th beat keeps the logo alive without leaving its corner
        beats = plan.get("beats") or []
        for b in beats[4::8]:
            if b + 0.3 < D:
                tl.append(f'tl.to("#logo",{{scale:1.08,duration:0.12,yoyo:true,repeat:1,ease:"power2.out"}},{b:.3f});')
    if plan.get("title"):
        t = plan["title"]
        fs = int(min(W, H) * 0.12)
        text = html.escape(t["text"])
        words = text.split() or [text]
        spans = "".join(f'<span class="w">{w}</span> ' for w in words)
        col = t.get("color", "#ffffff")
        shadow = "rgba(0,0,0,.6)" if col.lower() in ("#ffffff", "#fff", "white") else "rgba(255,255,255,.6)"
        css.append(f"#title{{position:absolute;left:5%;right:5%;top:50%;transform:translateY(-50%);text-align:center;"
                   f"color:{col};font-size:{fs}px;font-weight:900;line-height:1.05;letter-spacing:-0.02em;"
                   f"text-shadow:0 {max(2, fs // 24)}px {max(4, fs // 12)}px {shadow}}}")
        css.append(".w{display:inline-block;opacity:0}")
        css.append(f"#bar{{position:absolute;left:20%;right:20%;top:calc(50% + {int(fs * 0.75)}px);height:{max(4, fs // 10)}px;"
                   f"background:{col};transform-origin:0 50%;transform:scaleX(0)}}")
        dur = t["end"] - t["start"]
        els.append(f'<div id="title" class="clip" data-start="{t["start"]:.3f}" data-duration="{dur:.3f}">{spans}</div>')
        els.append(f'<div id="bar" class="clip" data-start="{t["start"]:.3f}" data-duration="{dur:.3f}"></div>')
        s, e = t["start"], t["end"]
        tl.append(f'tl.fromTo("#title .w",{{y:{int(fs * 0.6)},opacity:0,scale:0.6}},'
                  f'{{y:0,opacity:1,scale:1,duration:0.45,stagger:0.08,ease:"back.out(1.8)"}},{s + 0.05:.3f});')
        tl.append(f'tl.to("#bar",{{scaleX:1,duration:0.4,ease:"power3.out"}},{s + 0.25:.3f});')
        tl.append(f'tl.fromTo("#title",{{scale:1}},{{scale:1.06,duration:{max(0.3, dur - 0.9):.3f},ease:"none"}},'
                  f'{s + 0.5:.3f});')
        tl.append(f'tl.to("#title .w",{{y:-{int(fs * 0.4)},opacity:0,duration:0.25,stagger:0.04,ease:"power2.in"}},'
                  f'{max(s + 0.6, e - 0.35):.3f});')
        tl.append(f'tl.to("#bar",{{scaleX:0,duration:0.25,ease:"power2.in"}},{max(s + 0.6, e - 0.35):.3f});')
    # transition accents: a quick light sweep across soft transitions
    for i, sh in enumerate(plan["shots"][1:], 1):
        tr = sh["transition"]
        if tr["type"] == "cut" or tr["duration"] <= 0:
            continue
        d = tr["duration"]
        css.append(f"#sw{i}{{position:absolute;top:0;bottom:0;width:{int(W * 0.25)}px;left:-{int(W * 0.3)}px;"
                   "background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.35),rgba(255,255,255,0))}")
        els.append(f'<div id="sw{i}" class="clip" data-start="{sh["start"] - d / 2:.3f}" data-duration="{d:.3f}"></div>')
        tl.append(f'tl.fromTo("#sw{i}",{{x:0}},{{x:{int(W * 1.6)},duration:{d:.3f},ease:"power2.inOut"}},'
                  f'{sh["start"] - d / 2:.3f});')
    return f"""<!doctype html>
<html><head><meta charset="UTF-8"><script src="gsap.min.js"></script>
<style>{''.join(css)}</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{D:.3f}" data-width="{W}" data-height="{H}">
{chr(10).join(els)}
</div>
<script>window.__timelines=window.__timelines||{{}};const tl=gsap.timeline({{paused:true}});
{chr(10).join(tl)}
window.__timelines["main"]=tl;</script></body></html>"""


def render_overlay(proj, plan, work):
    ok, reason, browser, node = eng.hyperframes_status()
    if not ok:
        raise Fail(reason)
    work = Path(work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copyfile(eng.gsap_path(), work / "gsap.min.js")
    logo_name = ""
    if plan.get("logo"):
        src = proj / plan["logo"]["file"]
        logo_name = "logo" + src.suffix.lower()
        shutil.copyfile(src, work / logo_name)
    (work / "index.html").write_text(composition(plan, logo_name))
    frames = work / "frames"
    cmd = [node, str(eng.hf_cli()), "render", ".", "--format", "png-sequence", "-o", str(frames),
           "--fps", str(plan["fps"]), "--quiet"]
    log("rendering the HyperFrames text/motion layer ...")
    try:
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=60 * 60, env=eng.hf_env(browser))
    except subprocess.TimeoutExpired:
        raise Fail("HyperFrames took longer than 60 minutes")
    pngs = sorted(frames.glob("*.png"))
    if r.returncode != 0 or not pngs:
        tail = (r.stderr or r.stdout).strip().splitlines()
        raise Fail(f"HyperFrames exited {r.returncode}: {tail[-1] if tail else 'no frames'}")
    # normalise names for ffmpeg's image2 pattern
    for k, p in enumerate(pngs, 1):
        want = frames / f"frame_{k:06d}.png"
        if p != want:
            p.rename(want)
    return frames
