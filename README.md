# TrojanCut

TrojanCut is a Claude skill that edits videos. You give it a project zip holding your footage,
your logo, a few reference videos whose style you like, and (optionally) songs and sound effects,
plus a short notes.txt. You get back an MP4 that copies the references' cut rhythm, colour, text
style and motion effects (flashes, shakes, zoom punches, speed ramps), cut to the beat, within the
length you asked for.

Two skills work together:

- **/templatetrojancut** hands you the blank project template (`TrojanCut-Project.zip`) and the steps.
- **/trojancut** takes your filled-in project zip(s) and makes the edit. With no zip attached it
  hands out the same template.

The heavy work (analysis and rendering) runs in Python + ffmpeg. When Node.js and a Chrome/Edge
browser are available, the animated title, logo and motion-graphic layer is rendered with
HyperFrames; otherwise an ffmpeg fallback adds static text. Claude only reads small JSON files
and a capped set of small images, to keep Pro-plan usage low.

## Use it in claude.ai (chat)

1. Download both skill ZIPs: `trojancut.zip` and `templatetrojancut.zip` (from the GitHub release).
   Do not unzip them.
2. In claude.ai open **Settings > Capabilities** and turn on **code execution** (code execution
   and file creation).
3. Open **Customize > Skills**, click **Upload skill**, and upload `trojancut.zip`. Upload
   `templatetrojancut.zip` the same way. Make sure both are switched on.
4. In a new chat type **/templatetrojancut** and download `TrojanCut-Project.zip`.
5. Right-click it > **Extract All**. Put clips in `footage`, logos/images in `assets`, the videos
   to copy the style of in `refs`, songs in `music` (optional), your own sound effects in `sfx`
   (optional; put the type in the file name, like `whoosh_big.wav`).
6. Open `notes.txt`, answer each line after the colon and save (blank = Claude decides; write
   anything else under the last question).
7. Zip it: right-click the `TrojanCut-Project` folder > **Compress to ZIP file** (Windows 11) or
   **Send to > Compressed (zipped) folder** (Windows 10). Keep each zip under 500 MB; for a big
   shoot, make several zips and attach them together.
8. In a new chat type **/trojancut**, attach the zip(s) and send. Wait a few minutes, then download
   the MP4. Reply with changes if you want any.

## Use it in Claude Code (Windows, macOS, Linux)

1. Install Claude Code.
2. Open Claude Code, paste the repo URL `https://github.com/HenryNorcutt/TrojanCut` and say
   **"set this up"**. Claude Code clones the repo and runs the setup script for your system
   (`setup.ps1` on Windows uses winget for ffmpeg, Python 3.12 and Node 22; `setup.sh` on
   macOS/Linux). It installs what is missing, checks the render engine, and copies both skills
   into your Claude Code skills folder (`%USERPROFILE%\.claude\skills` or `~/.claude/skills`).
   Running it again changes nothing.
3. Restart Claude Code.
4. Use **/templatetrojancut** to get the template, fill it in as above, then run **/trojancut**
   with the path to your project folder or zip.

You can also run the setup yourself from the repo folder: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
(Windows) or `bash setup.sh` (macOS/Linux).

## The command line (for the curious)

`python3 skills/trojancut/scripts/tc.py <command>`:

| command | what it does |
|---|---|
| `setup` | installs pinned deps once; prints `engine: hyperframes` or `engine: ffmpeg` |
| `template --out D` | writes `D/TrojanCut-Project.zip` |
| `open ZIP... P` | unpacks project zip(s) into `P` and turns notes.txt into `P/brief.yaml` |
| `ingest P` | indexes clips, images, songs and sound effects; contact sheets |
| `analyze-refs P` | reference cuts, tempo, beats, colour LUT, motion effects |
| `autoplan P` | writes `P/work/plan.json` |
| `validate P` | checks plan.json |
| `render P` | renders `P/out/final.mp4` (`TROJANCUT_ENGINE=auto` or `ffmpeg`) |
| `check P` | measures the result into `P/out/report.json` |
| `package --out D` | builds `trojancut.zip` and `templatetrojancut.zip` |

Tests: `bash scripts/done.sh` runs every acceptance suite and the end-to-end check.

Third-party software: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
