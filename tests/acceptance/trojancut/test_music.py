"""D9: AB16 (several songs, parts, switches, music modes, fit)."""
import math
from pathlib import Path

import numpy as np
import pytest

from _helpers import (band_db, dominant_freq, engine_env, load, make_clip, make_ref, make_song, read_audio,
                      rms_db, run_pipeline, scene_cuts, seg, song_signal, write_brief, write_wav)

COLOURS = ["101010", "d02020", "20b020", "e0d020", "f0f0f0", "60a0ff"]
A = dict(bpm=100, freq=330, section_step=40)   # 0.6 s beats, pitch steps every 5 s
B = dict(bpm=150, freq=700, section_step=50)   # 0.4 s beats


def pitch_at(song, src_t):
    return song["freq"] + song["section_step"] * math.floor(src_t / 5.0)


def project(root, music, n_clips=6, clip_audio=None, ref_audio=None, **brief):
    root = Path(root)
    for i in range(n_clips):
        kw = {"audio_wav": clip_audio[i % len(clip_audio)]} if clip_audio else {}
        make_clip(root / "footage" / f"c{i + 1}.mp4", COLOURS[i % len(COLOURS)], w=320, h=180, dur=8,
                  moving=False, **kw)
    make_ref(root / "refs" / "ref.mp4", ["f0a040", "5a1808", "d06020"], 1.2, w=320, h=180, n_shots=10,
             audio=ref_audio, moving=False)
    make_song(root / "music" / "a.wav", A["bpm"], 40, A["freq"], section_step=A["section_step"])
    make_song(root / "music" / "b.wav", B["bpm"], 40, B["freq"], section_step=B["section_step"])
    b = dict(aspect="16:9", resolution=180, fps=25, music=music, logo="", title_text="", match="cuts",
             effects_intensity="low", sfx_amount="none", min_seconds=10, max_seconds=14)
    b.update(brief)
    write_brief(root, **b)
    run_pipeline(root, env=engine_env("ffmpeg"))
    return load(root, "plan.json"), load(root, "report.json"), read_audio(root / "out" / "final.mp4")


def grid_in_output(segment, period):
    """Output times of the song's beats (song beats at k*period in source time) inside this segment."""
    out = []
    k = math.ceil(segment["src_in"] / period - 1e-6)
    while k * period <= segment["src_out"] + 1e-6:
        out.append(segment["start"] + (k * period - segment["src_in"]))
        k += 1
    return out


def check_cuts_follow_grids(proj, plan, songs):
    segs = plan["music"]["segments"]
    measured = scene_cuts(proj / "out" / "final.mp4", 160, 90, 0.15)
    for cuts, tol, need in ((plan_cuts(plan), 0.06, 1.0), (measured, 0.1, 0.8)):
        on, total = 0, 0
        for c in cuts:
            inside = [(s, song) for s, song in zip(segs, songs) if s["start"] + 0.1 < c < s["end"] - 0.1]
            if len(inside) != 1:  # skip cuts during a crossfade, where two songs play
                continue
            s, song = inside[0]
            total += 1
            grid = grid_in_output(s, 60 / song["bpm"])
            on += min(abs(c - g) for g in grid) <= tol
        assert total >= 4, (cuts, segs)
        assert on >= need * total, f"{on}/{total} cuts on the playing song's grid"


def plan_cuts(plan):
    return [s["start"] for s in plan["shots"][1:]]


@pytest.fixture(scope="module")
def two_songs_cut(tmp_path_factory):
    proj = tmp_path_factory.mktemp("m") / "cut"
    music = [{"file": "music/a.wav", "part": [10, 16]}, {"file": "music/b.wav", "part": [5, 11]}]
    return (proj, *project(proj, music, song_switch="cut"))


def test_order_and_chosen_parts(two_songs_cut):
    proj, plan, report, x = two_songs_cut
    segs = plan["music"]["segments"]
    assert [Path(s["file"]).name for s in segs] == ["a.wav", "b.wav"]
    assert abs(segs[0]["src_in"] - 10) <= 0.61 and abs(segs[1]["src_in"] - 5) <= 0.41
    # pitch at output times proves which part of which song is playing
    assert dominant_freq(seg(x, 1.5, 4.0)) == pytest.approx(pitch_at(A, 12), abs=12)
    sw = segs[1]["start"]
    assert dominant_freq(seg(x, sw + 1.5, sw + 3.5)) == pytest.approx(pitch_at(B, 7.5), abs=12)
    assert report["ok"] is True


def test_hard_cut_join(two_songs_cut):
    proj, plan, report, x = two_songs_cut
    sw = plan["music"]["switches"][0]
    assert sw["type"] == "cut"
    t = sw["at"]
    seg_a = plan["music"]["segments"][0]
    assert min(abs(t - g) for g in grid_in_output(seg_a, 0.6)) <= 0.06, "cut not on a beat"
    fa, fb = pitch_at(A, seg_a["src_out"] - 0.2), pitch_at(B, plan["music"]["segments"][1]["src_in"] + 0.2)
    before, after = seg(x, t - 0.3, t - 0.03), seg(x, t + 0.03, t + 0.3)
    assert band_db(before, fa) > band_db(before, fb) + 20
    assert band_db(after, fb) > band_db(after, fa) + 20, "outgoing song still audible after a hard cut"


def test_cuts_follow_each_song_grid(two_songs_cut):
    proj, plan, report, x = two_songs_cut
    check_cuts_follow_grids(proj, plan, [A, B])


def test_quick_fade_join_on_bar_line(tmp_path):
    proj = tmp_path / "fade"
    music = [{"file": "music/b.wav", "part": [5, 11]}, {"file": "music/a.wav", "part": [10, 16]}]
    plan, report, x = project(proj, music, song_switch="fade")
    segs = plan["music"]["segments"]
    assert [Path(s["file"]).name for s in segs] == ["b.wav", "a.wav"]
    sw = plan["music"]["switches"][0]
    assert sw["type"] == "fade"
    beat = 60 / B["bpm"]
    assert 0.5 * beat <= sw["seconds"] <= 2.0 * beat
    bars = grid_in_output(segs[0], 4 * beat)
    assert min(abs(sw["at"] - g) for g in bars) <= 0.06, "fade does not start on a bar line"
    fb, fa = pitch_at(B, segs[0]["src_out"] - 0.1), pitch_at(A, segs[1]["src_in"] + 0.1)
    mid = seg(x, sw["at"] + 0.25 * sw["seconds"], sw["at"] + 0.75 * sw["seconds"])
    da, dbb = band_db(mid, fa), band_db(mid, fb)
    assert abs(da - dbb) < 18, (da, dbb)
    quiet = seg(x, sw["at"] - 1.0, sw["at"] - 0.2)
    assert band_db(mid, fa) > band_db(quiet, fa) + 10, "incoming song not fading in"
    check_cuts_follow_grids(proj, plan, [B, A])


def test_claude_decides_records_reason(tmp_path):
    proj = tmp_path / "auto"
    music = [{"file": "music/a.wav", "part": "auto"}, {"file": "music/b.wav", "part": "auto"}]
    plan, report, x = project(proj, music, song_switch="auto")
    for sw in plan["music"]["switches"]:
        assert sw["type"] in ("cut", "fade") and sw.get("reason", "").strip()


def test_auto_part_is_loud_window(tmp_path):
    proj = tmp_path / "loud"
    write_wav(proj / "music" / "c.wav", song_signal(120, 45, 500, loud=(22, 34)))
    plan, report, x = project(proj, [{"file": "music/c.wav", "part": "auto"}], min_seconds=8, max_seconds=10)
    s = plan["music"]["segments"][0]
    assert 21.4 <= s["src_in"] and s["src_out"] <= 34.6, s
    body = seg(x, 0.5, plan["duration"] - 0.5)
    assert band_db(body, 1000) > band_db(body, 500) - 12, "busy double-time layer missing: not the loud window"


def test_fit_trim_and_loop(tmp_path):
    long = [{"file": "music/a.wav", "part": [0, 20]}, {"file": "music/b.wav", "part": [0, 20]}]
    plan, report, x = project(tmp_path / "trim", long)
    assert 10 <= plan["duration"] <= 14
    assert "trim" in str(report["music_fit"]).lower()
    short = [{"file": "music/a.wav", "part": [10, 13]}, {"file": "music/b.wav", "part": [5, 7]}]
    plan, report, x = project(tmp_path / "loop", short)
    assert 10 <= plan["duration"] <= 14
    assert "loop" in str(report["music_fit"]).lower()
    assert rms_db(seg(x, plan["duration"] - 2.5, plan["duration"] - 0.5)) > -35, "silence after the parts"


def tone_wav(path, freq, rms=0.2, dur=8):
    t = np.arange(int(dur * 44100)) / 44100
    write_wav(path, rms * math.sqrt(2) * np.sin(2 * np.pi * freq * t))
    return path


def test_music_none_keeps_clip_audio(tmp_path):
    root = tmp_path / "none"
    tones = [tone_wav(tmp_path / f"t{f}.wav", f) for f in (600, 900, 1300)]
    plan, report, x = project(root, "none", n_clips=3, clip_audio=tones, min_seconds=6, max_seconds=9)
    tone_of = {f"footage/c{i + 1}.mp4": f for i, f in enumerate((600, 900, 1300))}
    checked = 0
    for s in plan["shots"]:
        if s["end"] - s["start"] >= 0.5:
            f = dominant_freq(seg(x, s["start"] + 0.15, s["end"] - 0.15))
            assert f == pytest.approx(tone_of[s["clip"]], abs=15), (s, f)
            checked += 1
    assert checked >= 3


def test_reference_audio(tmp_path):
    root = tmp_path / "ref"
    wav = tmp_path / "refsong.wav"
    make_song(wav, 100, 12, 523)
    plan, report, x = project(root, "reference", ref_audio=wav, min_seconds=6, max_seconds=10)
    assert dominant_freq(seg(x, 0.5, plan["duration"] - 0.5)) == pytest.approx(523, abs=12)
    segs = plan["music"]["segments"]
    assert len(segs) == 1 and Path(segs[0]["file"]).name == "ref.mp4"
    grid = grid_in_output(segs[0], 0.6)
    cuts = plan_cuts(plan)
    assert cuts and sum(min(abs(c - g) for g in grid) <= 0.08 for c in cuts) >= 0.8 * len(cuts)


@pytest.mark.parametrize("keep", [True, False])
def test_keep_clip_audio_level(tmp_path, keep):
    root = tmp_path / f"keep{keep}"
    sig = song_signal(110, 30, 300)
    write_wav(root / "music" / "s.wav", sig)
    level = float(np.sqrt(np.mean(sig ** 2)))
    tones = [tone_wav(tmp_path / "t1200.wav", 1200, rms=level)]
    plan, report, x = project(root, "music/s.wav", n_clips=3, clip_audio=tones, keep_clip_audio=keep,
                             min_seconds=6, max_seconds=9)
    body = seg(x, 0.5, plan["duration"] - 0.5)
    diff = band_db(body, 1200) - band_db(body, 300)
    if keep:
        assert -18 <= diff <= -6, f"clip audio should sit ~12 dB under the music, got {diff:.1f} dB"
    else:
        assert diff < -30, diff
