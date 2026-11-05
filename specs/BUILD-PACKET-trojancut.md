# BUILD-PACKET: trojancut
status: building
tier: L     runs-on: cloud     model: opus     effort: medium
repo: HenryNorcutt/TrojanCut   base-branch: main   work-branch: claude/trojancut, or the session's assigned claude/* branch if that name can't be pushed
packet-version: 7    created: 2026-11-05
v2 change: the primary flow is now a downloadable project template zip (AB12, AB13, AB11
  rewritten). Q&A in chat is only the fallback.
v3 change: a second skill, /templatetrojancut, hands out the template with step-by-step
  instructions (AB14); `package` builds both skill ZIPs (AB10).
v4 change: setup scripts install both skills for Claude Code (AB15); the GitHub Release is no
  longer RESERVED: the coordinator publishes it after verification (do not publish it yourself);
  G2 tester is Henry's brother.
v5 change: music is optional and may be several songs with chosen or auto-picked parts and
  cut/fade switches (AB16, D9); notes.txt music lines replaced (AB12); AB13 maps them.
v6 change: sound effects are back IN: a built-in pack we synthesize ourselves plus the user's own
  sfx/ folder (AB17, D10); template gains sfx/ and two notes lines (AB12, AB13).
v7 change: "Anything else:" is the last line of notes.txt and takes free text on any number of
  lines below it (AB12, AB13, AB11). Everything else unchanged.

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
types /trojancut in a normal claude.ai chat and gets a template project zip to download. He drops
footage, images, logos, references and music into its folders, fills in notes.txt, zips it, and
sends it back with /trojancut in one message. He gets back an MP4 that follows the references' cut
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
  footage or voice, tempo matching or time-stretching songs, lyric-aware cuts, drop-to-moment
  syncing, third-party sound-effect files in the repo, stem/vocal removal, multiple output variants, Premiere/Resolve timeline export, 4K, YouTube/URL
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
- `template --out D` - writes D/TrojanCut-Project.zip (see AB12).
- `open Z P` - unpacks one or more project zips Z (repeatable flag or several args) into P and
  writes P/brief.yaml from P/notes.txt (see AB13). brief.yaml stays the internal format the other
  commands read.
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
AB10: WHEN `package --out D` runs THE SYSTEM SHALL write D/trojancut.zip (under 15 MB, SKILL.md
  with name trojancut, description <= 1024 chars, no angle brackets, plus scripts/) and
  D/templatetrojancut.zip (top folder templatetrojancut/, SKILL.md with name templatetrojancut,
  same description rules, plus the bundled TrojanCut-Project.zip), neither containing
  node_modules or .pyc.
AB11: WHEN /trojancut is invoked in chat with no project zip attached THE SKILL SHALL (per
  SKILL.md) give the same template and steps as /templatetrojancut (AB14).
  WHEN invoked with project zip(s) attached THE SKILL SHALL run `open`, read brief.yaml `notes` and treat it as instructions that override defaults (not the
  answered questions), then the pipeline, look
  only at claude_images, optionally edit plan.json and re-run validate, render, check, and deliver
  the MP4 to /mnt/user-data/outputs when that dir exists. It SHALL ask the user at most one
  message of questions, and only when notes.txt is missing or contradicts the files (e.g. names a
  logo that isn't there). In Claude Code the same flow SHALL work with a local folder or zip path.
AB12: WHEN `template --out D` runs THE SYSTEM SHALL write TrojanCut-Project.zip containing
  folders footage/, assets/, refs/, music/, sfx/ (each with a one-line README.txt saying what goes
  in it; sfx/'s also says to put the type in the file name, e.g. whoosh_big.wav, impact_1.mp3), a top-level HOW-TO.txt (5 steps, plus: keep each zip under 500 MB, split big shoots into
  several zips and attach them together), and notes.txt with exactly these questions, one per
  line as "Question: answer", answers blank or defaulted as shown:
    Shortest length in seconds: 15
    Longest length in seconds: 30
    Shape (vertical / horizontal / square): vertical
    Music (none / reference audio / my songs): my songs
    Song order (file names separated by ;  blank = alphabetical):
    Song parts (e.g. song1.mp3 0:45-1:15; song2.mp3 auto  blank = Claude picks):
    Switch between songs (cut / quick fade / Claude decides): Claude decides
    Keep sound from the clips (yes / no): no
    Sound effects (none / some / lots): some
    Which sound effects (built-in / mine / both): both
    Copy from the references (cuts / color / text / everything): everything
    Effects amount (low / medium / high): medium
    Logo file (name in assets folder):
    Logo corner (top-left / top-right / bottom-left / bottom-right / none): top-right
    Title text at the start (blank = none):
    Must include:
    Avoid:
    Anything else (any notes or context, as many lines as you like below this one):
AB13: WHEN `open Z P` runs THE SYSTEM SHALL extract the zip(s) whether the folders sit at the
  zip root or inside one wrapper folder (Windows "Send to > Compressed folder"), ignore __MACOSX
  and dotfiles, merge several zips into one project, map notes.txt answers to brief.yaml
  (case-insensitive, extra spaces ignored, blank = default, "vertical" = 9:16, "everything" =
  full), map the music lines to brief.yaml (music stays a single path when there is exactly one
  song with no chosen part; otherwise a list of {file, part: "auto" | [start_s, end_s]} plus
  song_switch and keep_clip_audio; "my songs" with an empty music folder is an error; times
  accept m:ss, mm:ss and seconds), map the two sound-effect lines to sfx_amount and
  sfx_source ("mine" or "both" with an empty sfx/ folder falls back to built-in and says so;
  "mine" with no sfx/ folder is not an error), fill a missing logo answer when exactly one candidate file
  exists, and exit
  non-zero with a plain-English line naming the problem when notes.txt contradicts the files or
  a value is unreadable (e.g. shortest > longest). Everything after the "Anything else" line, to the end of the
  file, is kept verbatim (line breaks included) as brief.yaml `notes`; text there never breaks
  parsing even if it contains colons or looks like other questions.
AB16: WHEN the brief lists several songs THE SYSTEM SHALL play them in the given order, each
  using its chosen part or, for "auto", the highest-energy window (onset density and loudness)
  of the length the plan needs, joined by a hard cut on a beat ("cut") or a fade of about one
  beat that starts on a bar line ("quick fade"; "Claude decides" picks per pair and records why
  in plan.json); the output's cuts SHALL follow the beat grid of whichever song is playing; with
  music "none" the clips' own audio is kept; with "reference audio" the reference's soundtrack
  is used; with keep_clip_audio yes, clip audio sits about 12 dB under the music. Chosen parts
  that together fall outside min/max length are trimmed or looped to fit, and report.json says
  which. No time-stretching or tempo matching (OUT).
AB17: Sound effects.
  (a) Built-in pack: a script in the repo synthesizes it deterministically from numpy + ffmpeg
  (no downloads, no third-party files): at least whoosh, swoosh, riser, impact, sub drop, hit,
  glitch, pop and camera shutter, 2-4 variants each, short and normalised, total under 3 MB,
  shipped inside skills/trojancut/ with a manifest (name, type, duration, peak, loudness, tags).
  WHEN the script runs twice THE SYSTEM SHALL produce identical files.
  (b) WHEN ingest finds files in sfx/ THE SYSTEM SHALL index them with a type taken from the file
  name (whoosh, swoosh, riser, impact, hit, boom, drop, glitch, pop, click...) or, when the name
  has none, from the sound's shape (sharp attack = hit, rising level = riser, noise sweep =
  whoosh, else "other"), plus duration and loudness, in index.json (text only, no images).
  (c) WHEN sfx_amount is not none THE SYSTEM SHALL have autoplan place effects from the chosen
  source: a whoosh/swoosh on transitions, an impact/hit on the title reveal and on strong
  beats, a riser ending at each song switch; "some" about 1 per 4 cuts, "lots" about 1 per 2,
  never two overlapping; effects mixed about 6 dB under the music and never clipping. "both"
  prefers the user's file of a type over the built-in one. Claude may change placements in
  plan.json and validate checks every effect file exists. WHEN sfx_amount is none THE SYSTEM
  SHALL place no effects.
AB14: WHEN /templatetrojancut is invoked THE SKILL SHALL copy its bundled TrojanCut-Project.zip
  to /mnt/user-data/outputs (or the current folder in Claude Code), hand it to the user, and
  reply with these numbered steps in plain words (wording may differ, every step present):
  1. Download TrojanCut-Project.zip, right-click it > Extract All.
  2. Put clips in footage, logos/images in assets, the videos to copy the style of in refs,
     the song in music (optional).
  3. Open notes.txt, answer each line after the colon, save. Blank = let Claude decide.
  4. Zip it: right-click the TrojanCut-Project folder > Compress to ZIP file (Windows 11) or
     Send to > Compressed (zipped) folder (Windows 10). Keep each zip under 500 MB; for a big
     shoot, make several zips (e.g. move half the footage into a second copy of the folder).
  5. Open a new chat, type /trojancut, attach the zip(s), send.
  6. Wait while it analyses and renders (a few minutes for a 30 s edit), then download the MP4.
     To change it, reply with what to change; to start over, edit notes.txt and re-send.
  The skill SHALL need no network access and no installs (it only copies a file).
AB15: WHEN setup.ps1 (Windows) or setup.sh (macOS/Linux) runs from a clone of the repo THE SYSTEM
  SHALL install ffmpeg, Python and Node if missing (winget on Windows), run `tc.py setup`, and
  copy skills/trojancut and skills/templatetrojancut into the user's Claude Code skills folder
  (%USERPROFILE%\.claude\skills\ or ~/.claude/skills/), replacing older copies, so a second run
  changes nothing. The README's Claude Code section SHALL be: paste the repo URL into Claude Code
  and say "set this up" (CLAUDE.md gains a short project note below the guidelines telling
  Claude Code to run the setup script for the user's OS when asked to set the repo up), then
  restart Claude Code and use /templatetrojancut and /trojancut.
E2E: tests/e2e/test_e2e.py (both engines + package). Checked by: `python3 -m pytest tests/e2e -q`.
  The build agent must not write or edit this check.

## Done-conditions (become specs/trojancut/done.txt in the plan pass)
| id | command | expect | covers | must fail today |
|----|---------|--------|--------|-----------------|
| D1 | `python3 -m pytest tests/acceptance/trojancut/test_setup_ingest.py -q` | exit 0 | AB1, AB2 | yes |
| D2 | `python3 -m pytest tests/acceptance/trojancut/test_analyze.py -q` | exit 0 | AB3, AB4 | yes |
| D3 | `python3 -m pytest tests/acceptance/trojancut/test_plan.py -q` | exit 0 | AB5, AB6 | yes |
| D4 | `python3 -m pytest tests/acceptance/trojancut/test_render.py -q` | exit 0 | AB7, AB8, AB9 | yes |
| D5 | `python3 -m pytest tests/acceptance/trojancut/test_skill.py -q` | exit 0 | AB10, AB11 (static: SKILL.md steps, paths) | yes |
| D9 | `python3 -m pytest tests/acceptance/trojancut/test_music.py -q` | exit 0 | AB16 (synthetic songs at different BPMs and pitches: order kept, chosen part used (check pitch/onsets at the expected output times), auto part lands in the loud window, cut vs fade measurable at the join, cuts follow each song's grid, none / reference audio / keep_clip_audio cases) | yes |
| D10 | `python3 -m pytest tests/acceptance/trojancut/test_sfx.py -q` | exit 0 | AB17 (pack generated twice is byte-identical and under 3 MB, manifest matches files; user files classified by name and by shape with synthetic sharp/rising/sweep sounds; placement counts per amount; effects audible at planned times in the render (onset there); none = no effects; no clipping) | yes |
| D8 | `python3 -m pytest tests/acceptance/trojancut/test_install.py -q` | exit 0 | AB15 (setup.sh with HOME set to a temp dir installs both skills, second run is a no-op; setup.ps1 exists and references the same skill folders; CLAUDE.md keeps the verbatim guidelines intact above the project note) | yes |
| D7 | `python3 -m pytest tests/acceptance/trojancut/test_template_open.py -q` | exit 0 | AB12, AB13, AB14 (round trip: template -> fill -> zip with and without wrapper folder -> open -> pipeline renders; templatetrojancut SKILL.md has all six steps and its bundled zip equals `template` output) | yes |
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
M3 Plan + render + check + music + sfx - AB5..AB9, AB16, AB17 - done when D3, D4, D6, D9, D10.
M4 Skills + template + packaging + install + docs - AB10..AB15 - done when D5, D6, D7, D8; README covers (a) chat install:
   download both skill ZIPs, Customize > Skills > upload each, turn on code execution,
   /templatetrojancut to get the template, fill it, zip it, /trojancut with the zip; (b) Claude Code
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
- [RESERVED] Committing built ZIPs to the repo. (The GitHub Release is published by the
  coordinator after verification; the build never publishes it.)

## Open questions
(none)

## Human gates
G1 plan + acceptance-test approval. G1 auto-approve: yes.
G2 Henry's brother, after the coordinator publishes the Release: installs both skill ZIPs in his
   claude.ai chat and runs one real edit; optionally the Claude Code route on his Windows PC.
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
- One template zip + notes.txt, sent in one message, is the main flow (rejected: chat Q&A as the
  main flow, more turns and more Pro usage; rejected: YAML for the user-facing notes, a stray
  space breaks it).

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
