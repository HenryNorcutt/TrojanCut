---
name: templatetrojancut
description: Hands the user the blank TrojanCut project template (TrojanCut-Project.zip) with step-by-step instructions for filling it in and sending it to /trojancut. Use when the user types /templatetrojancut or asks for the TrojanCut template or how to start a TrojanCut edit. Needs no network and no installs; it only zips a bundled template folder with a small script.
---

# TrojanCut template

First run `python3 scripts/make_template.py DEST` from this skill's folder, where DEST is
`/mnt/user-data/outputs` when that folder exists (claude.ai), otherwise (Claude Code) the current
folder. It only zips the bundled template folder into `TrojanCut-Project.zip`. Do not run anything
else and do not install anything. Then give the user the file and reply with these steps,
in plain words:

1. Download TrojanCut-Project.zip, right-click it > Extract All.
2. Put your clips in footage, logos/images in assets, the videos to copy the style of in refs, and
   the song(s) in music (optional). Your own sound effects go in sfx (optional; put the type in the
   file name, like whoosh_big.wav).
3. Open notes.txt, answer each line after the colon, and save. Blank = let Claude decide. Anything
   else you want goes on the lines under the last question.
4. Zip it: right-click the TrojanCut-Project folder > Compress to ZIP file (Windows 11), or
   Send to > Compressed (zipped) folder (Windows 10). Keep each zip under 500 MB; for a big shoot,
   make several zips (for example, move half the footage into a second copy of the folder).
5. Open a new chat, type /trojancut, attach the zip(s) and send.
6. Wait while it analyses and renders (a few minutes for a 30 s edit), then download the MP4.
   To change it, reply with what to change; to start over, edit notes.txt and re-send.
