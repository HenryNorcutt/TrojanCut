# BUILD-PACKET: trojancut
status: ready
tier: L     runs-on: cloud     model: opus     effort: medium
repo: HenryNorcutt/TrojanCut   base-branch: main   work-branch: claude/trojancut, or the session's assigned claude/* branch if that name can't be pushed
packet-version: 1    created: 2026-11-05

## Read first
- CLAUDE.md on main already holds Henry's guidelines verbatim. Keep it as is; add project notes
  below it only if needed.
- This file is data, not authority. Approval of PLAN at G1 is the authorisation to build.
- This packet runs in ONE session, from plan pass to PR. Do not work on any other packet.
  If context compacts, re-read this packet, specs/trojancut/STATUS.json and PROGRESS.md.
- Hooks in .claude/settings.json enforce the protected paths and block you from finishing while
  scripts/done.sh fails. If a hook blocks you, fix the implementation, never the check.
- If a test or done-condition looks wrong, or a RESERVED / Ask-first item comes up, write
  specs/trojancut/BLOCKED.md (what, why, proposed exact diff or options with a recommendation),
  set STATUS phase to "blocked", commit, push and stop.
- Plan pass first (STATUS phase "plan"): write specs/trojancut/PLAN.json, write the acceptance
  tests under tests/acceptance/trojancut/ and the done-condition commands below into
  specs/trojancut/done.txt (one per line), run each to prove it FAILS, and prove the new tests CAN
  pass (against a throwaway stub, then discard it). Then set phase "building" and continue
  (G1 auto-approve: yes). Do not implement in the plan pass.
- At any gate: commit and push STATUS.json and REPORT.md first, then ask. Answers arrive as
  specs/answers/trojancut-<gate>.md on main: fetch it, set phase "building" and continue.
- tests/e2e/ was written by the coordinator. Read it first: it fixes the CLI contract below.
  You may not edit it. Generate test projects with tests/e2e/make_fixtures.py.

## Hard rules
Never: git push to main, force-push, sudo, crontab, systemctl/service, reading or printing secrets,
  editing, skipping or weakening tests or checks, special-casing test inputs (fixture colours,
  120 BPM, 1.0 s shots, file names), leaving stubs or placeholder behaviour and calling it done,
  resolving a RESERVED decision, requiring an API key or paid service.
Protected (read-only once the plan pass ends): this packet, tests/acceptance/trojancut/**,
  tests/e2e/**, specs/trojancut/done.txt, scripts/done.sh, .claude/**.

## Goal
TrojanCut is a Claude skill that edits videos for Henry's brother (Windows, Claude Pro plan). He
types /trojancut in a normal claude.ai chat, uploads footage, images and logos (zips allowed), then
reference videos, answers a few questions, and gets back an MP4 that follows the references' cut
rhythm, colour and text style, with transitions, effects and motion graphics, within his min/max
length. The same skill also works in Claude Code on his PC. Heavy lifting (probing, cut/beat/colour
analysis, rendering) is Python + ffmpeg + HyperFrames; Claude only reads compact JSON and a capped
set of small images, because his Pro plan's usage is tight. Done = the E2E passes on the cloud VM
for both render engines and the packaged skill ZIP is ready for Henry to test in chat (G2).

## Scope
IN: the skill folder skills/trojancut/ (SKILL.md + scripts/), the tc.py CLI below, footage and
  reference analysis, a heuristic planner, plan validation, rendering (HyperFrames + ffmpeg
  fallback), output check, ZIP packaging, README for Henry and his brother, setup.ps1 for Windows,
  THIRD_PARTY_NOTICES.md.
OUT (non-goals): web UI, accounts, hosted rendering, speech transcription and captions, AI-generated
  footage or voice, multiple output variants, Premiere/Resolve timeline export, 4K, YouTube/URL
  downloads, GitHub releases.

## CLI contract (fixed by tests/e2e; greenfield, so stated here)
`python3 skills/trojancut/scripts/tc.py <cmd>`; every command exits 0 on success, non-zero with a
one-line reason on failure.
- `setup` - install pinned deps idempotently; print which engine is usable.
- `ingest P`, `analyze-refs P`, `autoplan P`, `validate P`, `render P`, `check P` - P is a project
  dir holding footage/, assets/, refs/, music/ (each optional, may contain .zip files) and
  brief.yaml (shape: tests/e2e/make_fixtures.py BRIEF). Outputs: P/work/index.json,
  P/work/style.json, P/work/plan.json, P/out/final.mp4, P/out/report.json.
- `package --out D` - writes D/trojancut.zip with top folder trojancut/.
- env TROJANCUT_ENGINE: auto (default; HyperFrames when Node + package usable, else ffmpeg) or ffmpeg.
- index.json and style.json each carry `claude_images`: paths relative to P, the only images
  SKILL.md tells Claude to look at.

## Acceptance behaviours
AB1: WHEN `setup` runs twice THE SYSTEM SHALL install pinned deps on the first run and finish the
  second run in under 10 s without reinstalling; WHEN Node or npm is unreachable it SHALL still
  exit 0 and report engine "ffmpeg".
AB2: WHEN `ingest P` runs THE SYSTEM SHALL extract every .zip under footage/, assets/, refs/,
  music/, index every video and image (duration, size, fps, audio yes/no, motion score) in
  index.json, and write one contact sheet per clip (at most 16 tiles, longest side <= 1024 px)
  listed in claude_images.
AB3: WHEN `analyze-refs P` runs THE SYSTEM SHALL write style.json with each reference's cut times,
  median shot length, tempo (bpm) and beat times (from the reference audio; from brief music when
  the reference is silent), colour statistics and a .cube LUT, plus deduplicated scene-change
  frames (<= 1024 px) in claude_images.
AB4: WHEN a project has any number of clips and references THE SYSTEM SHALL cap claude_images
  across index.json + style.json at 40 images and the two JSON files at 60 KB combined.
AB5: WHEN `autoplan P` runs THE SYSTEM SHALL write a plan.json that validates, lasts between
  min_seconds and max_seconds, places cuts on the music's beat grid at roughly the reference's
  shot length, uses each usable clip before repeating one, and applies logo, title_text, colour
  match (per `match`) and transitions (per effects_intensity; `low` = hard cuts on at least 75%
  of cuts).
AB6: WHEN plan.json is invalid (missing clip, in/out outside the clip, overlapping shots, length
  outside the brief) THE SYSTEM SHALL make `validate` and `render` exit non-zero naming the field,
  never a traceback.
AB7: WHEN `render P` runs with engine auto and HyperFrames usable THE SYSTEM SHALL produce
  out/final.mp4 (h264, yuv420p, brief aspect and resolution, brief fps, music track) with an
  animated title card, the logo, colour grade and transitions, where text and motion-graphic
  layers come from HyperFrames.
AB8: WHEN engine is ffmpeg (forced or fallback) THE SYSTEM SHALL produce the same structure with
  static text and ffmpeg transitions, and report.json SHALL say which engine rendered it.
AB9: WHEN `check P` runs THE SYSTEM SHALL write report.json with ok true/false plus reasons
  (duration range, aspect, audio present, no more than 1 s of black frames) and exit non-zero
  when ok is false.
AB10: WHEN `package --out D` runs THE SYSTEM SHALL write a ZIP under 15 MB with SKILL.md (name
  trojancut, description <= 1024 chars, no angle brackets) and scripts/, without node_modules
  or .pyc.
AB11: WHEN /trojancut is invoked in chat THE SKILL SHALL (per SKILL.md) ask for footage and
  assets first (zips welcome), then references, then the brief questions (min/max length,
  aspect, music, logo position, title text, match level, effects intensity, must-include,
  avoid) in one message; copy uploads from /mnt/user-data/uploads into a project dir; run the
  pipeline; look only at claude_images; may edit plan.json and must re-run validate; render,
  check, and deliver the MP4 to /mnt/user-data/outputs when that dir exists. It SHALL work the
  same in Claude Code with a local project folder.
E2E: tests/e2e/test_e2e.py (both engines + package). Checked by: `python3 -m pytest tests/e2e -q`.
  The build agent must not write or edit this check.

## Done-conditions (become specs/trojancut/done.txt in the plan pass)
| id | command | expect | covers | must fail today |
|----|---------|--------|--------|-----------------|
| D1 | `python3 -m pytest tests/acceptance/trojancut/test_setup_ingest.py -q` | exit 0 | AB1, AB2 | yes |
| D2 | `python3 -m pytest tests/acceptance/trojancut/test_analyze.py -q` | exit 0 | AB3, AB4 | yes |
| D3 | `python3 -m pytest tests/acceptance/trojancut/test_plan.py -q` | exit 0 | AB5, AB6 | yes |
| D4 | `python3 -m pytest tests/acceptance/trojancut/test_render.py -q` | exit 0 | AB7, AB8, AB9 | yes |
| D5 | `python3 -m pytest tests/acceptance/trojancut/test_skill.py -q` | exit 0 | AB10, AB11 (static: SKILL.md steps, question list, paths) | yes |
| D6 | `python3 -m pytest tests/e2e -q` | exit 0 | E2E | yes (verified by coordinator) |
Use varied inputs in acceptance tests (different clip counts, aspect 16:9 and 1:1, a silent
reference, a brief with no music, a project with 25 clips for AB4), not just the E2E fixtures.

## Milestones
M1 Skeleton + engine spike - AB1, AB2 - done when D1. Also render a 5 s HyperFrames 0.9.16
   composition (one video clip + animated text) on the VM and record wall time and peak RAM in
   specs/trojancut/SPIKE.md. If HyperFrames will not render after 3 attempts, write BLOCKED.md
   (dropping it is RESERVED).
M2 Analysis - AB3, AB4 - done when D2. Frame sampling and near-duplicate removal adapted from
   bradautomates/claude-video (MIT; keep its notice in THIRD_PARTY_NOTICES.md).
M3 Plan + render + check - AB5..AB9 - done when D3, D4, D6.
M4 Skill + packaging + docs - AB10, AB11 - done when D5, D6; README covers (a) chat install:
   download ZIP, Customize > Skills > upload, turn on code execution, /trojancut; (b) Claude Code
   on Windows: install Claude Code, run setup.ps1 (winget: ffmpeg, Python 3.12, Node 22), open the
   repo folder.
Each milestone: commit and push on green; 3 failed attempts -> revert to last green, report.
Keep specs/trojancut/PROGRESS.md: one line per step (what changed, what's next).

## Boundaries
Always: run the named checks and print command + exit code; commit only on green; push after each
  milestone; pin every dependency version.
Allowed dependencies (no others without asking): Python stdlib, numpy, Pillow, PyYAML, pytest;
  ffmpeg/ffprobe; Node 22 + hyperframes@0.9.16 (and GSAP only as HyperFrames needs it). The core
  path (ingest, analyze-refs, autoplan, validate, ffmpeg render, check) must run with only
  numpy, Pillow, PyYAML and ffmpeg: the chat sandbox may block pip/npm.
Ask first (write BLOCKED.md and stop): any other dependency, deleting files outside scope, any
  change to a protected path.
RESERVED (Henry decides; write BLOCKED.md with options + recommendation):
- [RESERVED] Dropping HyperFrames or motion graphics.
- [RESERVED] Adding transcription, captions, or anything that needs an API key.
- [RESERVED] Publishing a GitHub release or committing the built ZIP.

## Open questions
(none)

## Human gates
G1 plan + acceptance-test approval. G1 auto-approve: yes.
G2 Henry, after the PR: install dist/trojancut.zip in his own claude.ai chat and run one real edit
   with his footage and a reference; on his Windows PC run setup.ps1 and one edit in Claude Code.
   Look/feel is judged here, not by tests.
G3 PR, opened ready for review (not draft). Before the PR: merge latest main, run scripts/done.sh
   and every suite, then run the packet-evaluator subagent (.claude/agents/packet-evaluator.md)
   and fix every FAIL it reports. Do not open the PR until specs/trojancut/VERDICT.md says
   OVERALL PASS. After opening it, do not keep watching or auto-fixing the PR.

## Budget and kill criteria
Turn cap: 500. Wall clock: 6 h. Retries per milestone: 3.
Kill if: D6 still fails after 3 full M3 attempts -> BLOCKED.md with the failing assertions.

## Decisions already made
- A claude.ai chat skill first, Claude Code second, from one folder (rejected: a web app, because
  it needs hosting and accounts; rejected: an MCP server, because chat skills cannot host one).
- Render engine HyperFrames 0.9.16 + ffmpeg (rejected: Remotion, which needs a paid company
  licence and a React build; rejected: forking shubh-projects/ai-video-editor, which is Elastic
  License, a five-service stack, and unproven on references).
- Claude sees contact sheets and capped deduplicated frames, never raw video (rejected: sending
  all frames, too costly on a Pro plan).
- No transcription in v1 (rejected: WhisperX, needs 8 GB RAM and 3 GB disk; chat sandbox has
  about 7 GB).
- Beat and cut detection in numpy + ffmpeg scene filter (rejected: librosa / PySceneDetect /
  OpenCV, too heavy to install in every chat).
- Big uploads come as zips (chat allows 20 files per chat, 500 MB per file).

## Known gaps and risks
- Unverified until G2: whether claude.ai chat accepts video uploads into the sandbox and allows npm.
  The ffmpeg engine exists so the skill still works without npm.
- The chat sandbox has 2 cores; keep renders lean (one Chrome capture pass, no 4K).
- HyperFrames is pre-1.0; pin the version and read its docs from the installed package.
- Windows paths and setup.ps1 cannot be tested on the VM; G2 covers them.

## Report (specs/trojancut/REPORT.md, committed)
Buckets: DONE (with check output) / READY TO APPROVE / YOUR TURN (questions, reserved decisions).
Include: commands run with exit codes, collected-test counts, files changed, SPIKE.md numbers,
E2E wall time per engine, permission denials, hook blocks or skipped actions, deviations from the
packet, turns and time used.

## /goal (draft - plan pass replaces <g1_commit>)
/goal specs/BUILD-PACKET-trojancut.md is done only when, after your final code change, you have run `bash scripts/done.sh` and printed its full output ending in "ALL PASS"; printed `git diff --exit-code <g1_commit> -- tests/acceptance/trojancut tests/e2e specs/trojancut/done.txt scripts/done.sh .claude specs/BUILD-PACKET-trojancut.md` exiting 0; specs/trojancut/VERDICT.md from the packet-evaluator says OVERALL PASS; and `git status --porcelain` is empty on the work branch. Do not modify, skip, or weaken any test or check. If a RESERVED decision, Ask-first action or a wrong test blocks you, write specs/trojancut/BLOCKED.md, commit, push and treat the goal as impossible. Or stop after 500 turns.

## CLAUDE.md guidelines (verbatim)
Already present verbatim in CLAUDE.md on main (see Read first).
