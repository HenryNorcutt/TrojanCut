# TrojanCut progress

- 09:20 Cloned repo, branch claude/trojancut. Read packet v1, e2e, hooks. Next: plan pass.
- 09:40 Pre-plan feasibility: hyperframes@0.9.16 installs from npm; chrome-headless-shell download blocked (storage.googleapis.com), renders with system Chrome via HYPERFRAMES_BROWSER_PATH; transparent png-sequence overlay works. Next: plan.
- 10:05 Merged packet v2..v6 from main (template zip, /templatetrojancut, install scripts, multi-song music, SFX). Next: write PLAN.json, acceptance tests D1-D5, D7-D10, done.txt.
- 10:50 Merged packet v7. Wrote acceptance tests (97 collected, 9 files + _helpers.py) and done.txt (D1-D5, D7-D10, D6). Every done-condition exits 1 today (see REPORT.md). Helper self-test on ground-truth media passes. SPIKE.md recorded. G1 auto-approved; phase -> building. Next: M1 (setup, ingest).
- 11:20 REOPENED plan pass: make_clip's drawbox x=f(t) is evaluated once by ffmpeg 6.1, so 'moving' fixtures were static (motion test unpassable). Fixing the fixture with overlay (per-frame eval) and finishing the 'tests can pass' proof before any implementation commit.
- 11:30 Fixture fixed (overlay-based moving box; verified box x moves 27->107->73 px). Plan pass closed again; phase -> building. Implementation files were held out of this commit.
- 11:55 M1 green: D1 9 passed (exit 0). setup installs hyperframes@0.9.16 via npm ci --ignore-scripts into TROJANCUT_HOME, finds system Chrome, smoke-renders once, stamps; ingest indexes + contact sheets. Next: M2 analyze-refs.
- 12:00 Merged packet v8 (AB18 motion fx). Reopened plan step to add test_motion_fx.py + D11 (authorised).
- 12:25 D11 added (test_motion_fx.py, 14 tests): fails today (exit 1: 5 failed, 9 errors). Throwaway ffmpeg stub proved render-side measures can pass (flash +148 luma, ramp vel 133->42 px/s, shake jitter 56 vs 1.7, no borders). Fixtures verified by phase correlation. Plan step closed; phase -> building. M2 (D2 7 passed) committed next.
- 12:30 M2 green: D2 7 passed (exit 0, 95 s). analyze-refs: scene-score cuts, numpy beat tracker, colour stats + 17^3 LUT, claude-video-derived frame dedupe, 60 KB budget with sidecars. Next: M3 (plan, render, check, music, sfx, motion fx).
