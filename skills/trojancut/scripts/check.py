"""`check P`: measure out/final.mp4 against the brief -> out/report.json; exit 1 when not ok."""
import json
import re
import subprocess

from common import ASPECTS, ffprobe, load_brief, project_dir, write_json

BLACK_LIMIT = 1.0


def black_seconds(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-an", "-vf",
                        "scale=160:-2,blackdetect=d=0.04:pic_th=0.97:pix_th=0.08", "-f", "null", "-"],
                       capture_output=True, text=True)
    total = 0.0
    for m in re.finditer(r"black_duration:([0-9.]+)", r.stderr):
        total += float(m.group(1))
    return round(total, 3)


def check(proj):
    proj = project_dir(proj)
    brief = load_brief(proj)
    final = proj / "out" / "final.mp4"
    reasons, checks = [], {}
    if not final.exists():
        report = {"ok": False, "reasons": ["out/final.mp4 is missing; run render first"], "checks": {}}
        write_json(proj / "out" / "report.json", report)
        print("error: out/final.mp4 is missing; run render first")
        return 1
    info = ffprobe(final)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"].get("duration", 0))
    lo, hi = brief["min_seconds"], brief["max_seconds"]
    checks["duration"] = {"seconds": round(dur, 3), "min": lo, "max": hi, "ok": lo - 0.25 <= dur <= hi + 0.25}
    if not checks["duration"]["ok"]:
        reasons.append(f"duration {dur:.2f}s is outside {lo:g}-{hi:g}s")
    aw, ah = ASPECTS[brief["aspect"]]
    w, h = (v["width"], v["height"]) if v else (0, 0)
    ok_aspect = bool(v) and abs(w / max(h, 1) - aw / ah) < 0.02
    checks["aspect"] = {"width": w, "height": h, "want": brief["aspect"], "ok": ok_aspect}
    if not ok_aspect:
        reasons.append(f"aspect {w}x{h} does not match {brief['aspect']}")
    checks["audio"] = {"present": has_audio, "ok": has_audio}
    if not has_audio:
        reasons.append("audio track missing")
    blk = black_seconds(final)
    checks["black"] = {"seconds": blk, "limit": BLACK_LIMIT, "ok": blk <= BLACK_LIMIT}
    if blk > BLACK_LIMIT:
        reasons.append(f"black frames for {blk:.2f}s (limit {BLACK_LIMIT:g}s)")
    codec_ok = bool(v) and v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"
    checks["codec"] = {"video": v.get("codec_name") if v else None, "pix_fmt": v.get("pix_fmt") if v else None,
                       "ok": codec_ok}
    if not codec_ok:
        reasons.append("video is not h264/yuv420p")
    rinfo = {}
    rj = proj / "work" / "render.json"
    if rj.exists():
        rinfo = json.loads(rj.read_text())
    plan = {}
    pj = proj / "work" / "plan.json"
    if pj.exists():
        plan = json.loads(pj.read_text())
    report = {"ok": not reasons, "reasons": reasons, "checks": checks,
              "engine": rinfo.get("engine"), "fallback_reason": rinfo.get("fallback_reason", ""),
              "layers": rinfo.get("layers", {}), "render_seconds": rinfo.get("render_seconds"),
              "music_fit": rinfo.get("music_fit", (plan.get("music") or {}).get("fit", "")),
              "music_switches": (plan.get("music") or {}).get("switches", []),
              "sfx_count": len(plan.get("sfx") or []),
              "motion_effects": sum(len(s.get("effects") or []) + (1 if s.get("speed") else 0)
                                    for s in plan.get("shots", []))}
    write_json(proj / "out" / "report.json", report)
    if reasons:
        print("check FAILED: " + "; ".join(reasons))
        return 1
    print(f"check OK: {dur:.2f}s {w}x{h}, audio, {blk:.2f}s black, engine {report['engine']}")
    return 0
