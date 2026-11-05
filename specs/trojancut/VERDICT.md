# VERDICT: trojancut (packet v8)

Evidence from this session: the protected-path diff against 1fdc0c0 exited 0. I ran the E2E (3 passed, 256 s) and D1..D5, D7..D11 (all pass). I also ran a fresh pipeline on new fixtures with a changed brief (1:1, 12-20 s, high effects, sfx lots) and ran the package and template commands. A grep for TODO, stub, skip, xfail and NotImplemented in skills, scripts and tests found nothing. I found no hard-coded fixture values in the skill scripts; the 120 BPM matches are a tempo prior and a fallback in audio.py, and the planner reads its values from the analysis.

| AB | Result | Evidence |
|----|--------|----------|
| AB1 | PASS | D1 9 passed (covers the twice-run timing and the no-Node case). `tc.py setup` printed "hyperframes 0.9.16 already installed, engine: hyperframes" and exited 0. |
| AB2 | PASS | D1 passed. On the fresh run, ingest extracted more.zip and indexed 6 clips and 1 image, with 6 contact sheets. |
| AB3 | PASS | D2 7 passed. Fresh run: median shot 1.0 s, 120 BPM, 4 deduplicated frames, written to style.json. |
| AB4 | PASS | D2 passed, including the 25-clip case. |
| AB5 | PASS | D3 14 passed. Fresh plan: 16 shots over 16.00 s (limits 12-20), beats on a 0.5 s grid, logo, title, LUT grade, soft transitions and sfx all present. |
| AB6 | PASS | I corrupted a shot's `in` to 999. `validate` and `render` both exited 1 with "plan.json shots[1].out (1.30) must be after in (999.00)" and no traceback. D3 also passed. |
| AB7 | PASS | D4 11 passed. Fresh HyperFrames render: h264, yuv420p, 1080x1080, 30 fps, aac audio, 16.03 s. I extracted frames and saw an animated title ("TROJAN" mid-pop), the rotated logo mid-animation, and a flash frame. report.json says engine hyperframes, with title and logo layers from hyperframes. |
| AB8 | PASS | `TROJANCUT_ENGINE=ffmpeg render` rendered with the ffmpeg engine; `check` OK; report.json engine "ffmpeg". D4 passed. |
| AB9 | PASS | `check` wrote report.json with ok true, duration, aspect, audio, black and codec checks. D4 covers the non-zero exit when ok is false. |
| AB10 | PASS | `package` wrote trojancut.zip (1.42 MB, SKILL.md name trojancut, scripts/ present) and templatetrojancut.zip (templatetrojancut/SKILL.md plus TrojanCut-Project.zip). I counted 0 .pyc or node_modules entries. D5 passed. |
| AB11 | PASS | D5 7 passed (static check of SKILL.md steps and paths). Both SKILL.md files are present and consistent with the CLI. The chat flow itself is only checkable at G2. |
| AB12 | PASS | `template` output has footage, assets, refs, music and sfx README.txt files, HOW-TO.txt, and notes.txt with exactly the 17 specified lines, ending in "Anything else". D7 19 passed. |
| AB13 | PASS | D7 round trip passed (with and without a wrapper folder, merge, mapping, error cases). |
| AB14 | PASS | The zip bundled in templatetrojancut is byte-identical to `template` output (cmp). D7 checks all six steps. |
| AB15 | PASS | D8 6 passed. setup.sh, setup.ps1 and the CLAUDE.md project note exist, and the guidelines above the note are unchanged. README changes are in scope. |
| AB16 | PASS | D9 11 passed. |
| AB17 | PASS | D10 13 passed. Fresh render: 8 sfx placed, sfx_count 8 in report.json; the shipped pack is 27 wav files plus manifest.json, about 1.4 MB. |
| AB18 | PASS | D11 14 passed. The fresh plan carries per-shot effects such as shake with at, duration and strength, and the render applied them. |
| E2E | PASS | 3 passed, covering both engines and package. |

Scope: git status is clean. Changes are limited to the skills, scripts, README, CLAUDE.md note, THIRD_PARTY_NOTICES, setup scripts and specs/trojancut. No new dependencies and no committed ZIPs.

OVERALL PASS
