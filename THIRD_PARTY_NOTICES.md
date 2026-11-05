# Third-party notices

TrojanCut ships or installs the following third-party software.

## claude-video (MIT)

Scene-frame sampling, even sampling and near-duplicate frame removal in
`skills/trojancut/scripts/analyze.py` are adapted from
[bradautomates/claude-video](https://github.com/bradautomates/claude-video)
(`skills/watch/scripts/frames.py`).

```
MIT License

Copyright (c) 2026 Bradley Bonanno

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## HyperFrames 0.9.16 (Apache-2.0)

Installed by `tc.py setup` from npm (`hyperframes@0.9.16`, pinned by
`skills/trojancut/engine/package-lock.json`) into the user's cache folder; not bundled in the
skill ZIP. Source: https://github.com/heygen-com/hyperframes. Licensed under the Apache License,
Version 2.0 (https://www.apache.org/licenses/LICENSE-2.0). TrojanCut runs it with
`DO_NOT_TRACK=1`.

## GSAP 3.15.0

Used only through the copy HyperFrames vendors in its own package
(`hyperframes/dist/vendor/npm/gsap@3.15.0`), loaded inside HyperFrames compositions. GSAP is
distributed under its own "no charge" standard license (https://gsap.com/standard-license).

## Python packages (installed, not bundled)

- numpy 2.5.3 - BSD-3-Clause
- Pillow 12.3.0 - MIT-CMU (HPND)
- PyYAML 6.0.3 - MIT

## FFmpeg

TrojanCut calls the user's installed `ffmpeg` / `ffprobe` executables; it does not bundle them.

## Built-in sound effects

The sounds in `skills/trojancut/sfx/` are synthesized by `skills/trojancut/scripts/make_sfx.py`
in this repository. No third-party audio is included.
