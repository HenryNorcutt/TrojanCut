# HyperFrames 0.9.16 engine spike (M1)

VM: 2 vCPU Xeon @ 2.10 GHz, 7.8 GB RAM, no GPU, Node v22.23.4, ffmpeg 6.1.1, system Chrome at
/usr/bin/google-chrome. Peak RAM = summed RSS of the render process tree, sampled every 0.2 s from
/proc (GNU time is not installed).

| attempt | composition | result | wall | peak RAM |
|---|---|---|---|---|
| 1 | 5 s, 1080x1920, one video clip + GSAP-animated text | FAILED: HyperFrames tried to download chrome-headless-shell 152 from storage.googleapis.com (not reachable from this VM) | 1.4 s | 356 MB |
| 2 | same, with HYPERFRAMES_BROWSER_PATH=/usr/bin/google-chrome | OK: h264, yuv420p, 1080x1920, 30 fps, 5.000 s; title animates in and out | 23.9 s | 1202 MB |
| 3 | 10 s transparent overlay (animated logo + title), `--format png-sequence` | OK: 300 RGBA PNGs, alpha 0 outside layers; static-frame dedup reused 266/300 frames | 9.8 s | 1229 MB |

Findings that shape the design:
- The perf-optimised BeginFrame path needs chrome-headless-shell, which cannot be downloaded
  here (and may not be in the chat sandbox or on Windows). Regular Chrome works through the
  screenshot capture path. `tc.py setup` therefore detects a system Chrome / Chromium / Edge
  (PATH plus the usual Windows install paths) and passes it as HYPERFRAMES_BROWSER_PATH; with no
  browser it reports engine "ffmpeg".
- HyperFrames renders the text and motion-graphic layers as a transparent PNG sequence; ffmpeg
  composites it over the graded, cut footage. That keeps video decoding out of Chrome (the
  slowest part of attempt 2) and lets both engines share one base render.
- Low-memory mode is auto-selected at <= 8 GB RAM (1 worker), which suits the 2-core chat sandbox.
- GSAP comes from the copy HyperFrames vendors (dist/vendor/npm/gsap@3.15.0), so no CDN fetch.
- DO_NOT_TRACK=1 is set on every HyperFrames call (it has opt-out telemetry).
