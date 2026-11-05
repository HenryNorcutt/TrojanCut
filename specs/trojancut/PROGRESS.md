# TrojanCut progress

- 09:20 Cloned repo, branch claude/trojancut. Read packet v1, e2e, hooks. Next: plan pass.
- 09:40 Pre-plan feasibility: hyperframes@0.9.16 installs from npm; chrome-headless-shell download blocked (storage.googleapis.com), renders with system Chrome via HYPERFRAMES_BROWSER_PATH; transparent png-sequence overlay works. Next: plan.
- 10:05 Merged packet v2..v6 from main (template zip, /templatetrojancut, install scripts, multi-song music, SFX). Next: write PLAN.json, acceptance tests D1-D5, D7-D10, done.txt.
- 10:50 Merged packet v7. Wrote acceptance tests (97 collected, 9 files + _helpers.py) and done.txt (D1-D5, D7-D10, D6). Every done-condition exits 1 today (see REPORT.md). Helper self-test on ground-truth media passes. SPIKE.md recorded. G1 auto-approved; phase -> building. Next: M1 (setup, ingest).
- 11:20 REOPENED plan pass: make_clip's drawbox x=f(t) is evaluated once by ffmpeg 6.1, so 'moving' fixtures were static (motion test unpassable). Fixing the fixture with overlay (per-frame eval) and finishing the 'tests can pass' proof before any implementation commit.
- 11:30 Fixture fixed (overlay-based moving box; verified box x moves 27->107->73 px). Plan pass closed again; phase -> building. Implementation files were held out of this commit.
