from pathlib import Path

import pytest

from studio.media import audio, captions, ffmpeg, render, storyboard
from studio.media.tts import EspeakNGProvider, WordTiming, _proportional_events, load_lexicon, narrate

from .conftest import REPO

SECTIONS = [
    {"name": "HOOK", "sentences": [{"text": "In 1970, Conway bet fifty dollars that this could not happen."}]},
    {"name": "PAYOFF", "sentences": [{"text": "A team at MIT won the money. It is Turing complete."}]},
]


@pytest.fixture(scope="module")
def narration(tmp_path_factory):
    out = tmp_path_factory.mktemp("tts") / "voice.wav"
    return narrate(EspeakNGProvider("en-us"), SECTIONS, out_wav=out, wpm=165, pitch=50, sentence_pause=0.28,
                   section_pause=0.5, hook_pitch_delta=6, lexicon=load_lexicon(REPO / "config" / "pronunciations.yaml"))


def test_word_level_timestamps(narration):
    written = [w for s in SECTIONS for x in s["sentences"] for w in x["text"].split()]
    assert [w.word for w in narration.words] == written          # captions keep original spelling
    starts = [w.start for w in narration.words]
    assert starts == sorted(starts) and all(w.end > w.start for w in narration.words)
    assert narration.words[-1].end <= narration.duration
    assert narration.words[0].start < 0.5                          # hook starts immediately
    hook_end = max(w.end for w in narration.words if w.section == "HOOK")
    payoff_start = min(w.start for w in narration.words if w.section == "PAYOFF")
    assert payoff_start - hook_end >= 0.45                         # section pause respected
    assert ffmpeg.probe(narration.audio_path).duration == pytest.approx(narration.duration, abs=0.05)


def test_proportional_fallback_is_monotonic():
    ev = _proportional_events("one two three four", 2.0)
    assert [p for p, _ in ev] == [0, 4, 8, 14] and [t for _, t in ev] == sorted(t for _, t in ev)


# -- captions ----------------------------------------------------------------------------
STYLE = {"max_words_per_chunk": 3, "max_chars_per_chunk": 18, "min_chunk_seconds": 0.35, "font": "DejaVu Sans",
         "font_size": 86, "primary_color": "#FFFFFF", "highlight_color": "#FFD23F", "outline_color": "#000000",
         "margin_v": 620, "margin_lr": 110, "word_highlight": True}


def test_caption_chunks_timing_and_formats(narration):
    chunks = captions.chunk_words(narration.words, STYLE)
    assert all(len(c.words) <= 3 for c in chunks)
    assert all(len(c.text) <= 18 or len(c.words) == 1 for c in chunks)
    assert captions.validate(chunks, narration.words, narration.duration) == []
    assert not any(c.text.endswith(",") and i + 1 < len(chunks) and c.words[-1]["word"] != c.text.split()[-1]
                   for i, c in enumerate(chunks))
    ass = captions.to_ass(chunks, STYLE, (1080, 1920))
    assert "PlayResY: 1920" in ass and ass.count("Dialogue:") >= len(chunks) and "\\c&H" in ass
    srt = captions.to_srt(chunks)
    assert srt.startswith("1\n00:00:00,") and "-->" in srt
    broken = list(chunks)
    broken[1] = captions.Chunk(broken[1].text, broken[0].start, broken[1].end, broken[1].words)
    assert any("overlaps" in p for p in captions.validate(broken, narration.words, narration.duration))


def test_caption_styles_config_loads(ctx):
    style = captions.load_style(ctx)
    assert style["name"] == "bold_center" and style["margin_v"] > 0
    for name in ("clean_lower", "boxed_upper"):
        assert "Style: Caption" in captions.to_ass([captions.Chunk("A B", 0, 1, [{"word": "A", "start": 0, "end": .5},
                                                                               {"word": "B", "start": .5, "end": 1}])],
                                                    captions.load_style(ctx, name), (1080, 1920))


# -- audio -------------------------------------------------------------------------------
def test_audio_tracks_mix_loudness(ctx, narration, tmp_path):
    tone = tmp_path / "licensed_tone.wav"  # self-generated "music" for the test
    ffmpeg.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-c:a", "pcm_s16le", str(tone)])
    tracks = audio.build_tracks(ctx, voice_raw=Path(narration.audio_path), out_dir=tmp_path / "a",
                                duration=narration.duration, music_file=tone)
    durs = {k: ffmpeg.probe(tracks[k]).duration for k in ("voice", "music", "sfx", "ambience", "mix")}
    assert max(durs.values()) - min(durs.values()) < 0.1
    loud = tracks["mix_loudness"]
    assert abs(loud["integrated_lufs"] - (-14.0)) <= 2.0
    assert loud["true_peak_db"] <= -1.0
    assert not ffmpeg.detect_silence(tracks["music"], min_duration=1.0)  # music looped to full length


# -- storyboard ----------------------------------------------------------------------------
def _src(i, tags, w=1080, h=1920, attribution=False):
    return {"source_id": f"s{i}", "media_type": "video", "local_path": f"/x/{i}.mp4", "duration": 10.0, "width": w,
            "height": h, "title": " ".join(tags), "tags_json": tags, "description": "", "analysis_json": {}}


def test_storyboard_respects_limits(ctx):
    sentences = [{"section": "HOOK", "text": "A glider moves.", "start": 0.15, "end": 2.0},
                 {"section": "DEVELOPMENT", "text": "The rules of the grid decide which cells live and die, " * 3,
                  "start": 2.3, "end": 16.0},
                 {"section": "PAYOFF", "text": "The glider gun never stops.", "start": 16.3, "end": 19.0}]
    sources = [_src(1, ["glider", "moves"]), _src(2, ["glider gun", "gun"], w=1920, h=1080)]
    lic = {"s2": {"attribution_required": 1, "attribution_text": "Gun by X, CC BY 4.0", "license_type": "CC-BY-4.0"}}
    scenes = storyboard.build_storyboard(sentences=sentences, total_duration=19.6, sources=sources, licenses=lic,
                                         facts_by_id={}, sentence_facts=[[], [], []], hook_title="A glider",
                                         topic="Life", cfg=ctx.cfg)
    assert scenes[0]["start_time"] == 0 and scenes[-1]["end_time"] == 19.6
    assert all(a["end_time"] == pytest.approx(b["start_time"]) for a, b in zip(scenes, scenes[1:]))
    st = storyboard.screen_time(scenes)
    assert st["longest_source_shot"] <= ctx.cfg.get("source_policy.max_continuous_source_seconds") + 1e-6
    assert st["source_ratio"] <= ctx.cfg.get("source_policy.max_source_screen_ratio") + 1e-6
    assert any(g["type"] == "title_card" for g in scenes[0]["graphics"])
    payoff = [s for s in scenes if s["section"] == "PAYOFF" and s["visual_type"] == "footage"]
    assert payoff and payoff[0]["visual_source"] == "s2" and payoff[0]["framing"] == "blur_fill"
    assert any(g["type"] == "attribution" for g in payoff[0]["graphics"])
    no_sources = storyboard.build_storyboard(sentences=sentences, total_duration=19.6, sources=[], licenses={},
                                             facts_by_id={}, sentence_facts=[[], [], []], hook_title="x", topic="t",
                                             cfg=ctx.cfg)
    assert all(s["visual_type"] == "graphic" for s in no_sources)


# -- render ----------------------------------------------------------------------------------
def test_render_produces_youtube_ready_vertical_mp4(ctx, fixture_media, narration, tmp_path):
    ctx.cfg.data["production"]["x264_preset"] = "ultrafast"
    dur = narration.duration
    clip = fixture_media / "library" / "life_landscape_soup.mp4"
    src = {"source_id": "s1", "local_path": str(clip), "duration": 8.0}
    half = round(dur / 2, 3)
    scenes = [
        {"idx": 0, "section": "HOOK", "start_time": 0.0, "end_time": half, "visual_type": "footage",
         "visual_source": "s1", "source_in": 1.0, "framing": "blur_fill", "effect": "punch_in",
         "graphics": [{"type": "title_card", "text": "A bet about growth", "end": 2.0},
                      {"type": "attribution", "text": "Footage: self-generated (CC0)"}]},
        {"idx": 1, "section": "PAYOFF", "start_time": half, "end_time": dur, "visual_type": "graphic",
         "effect": "slow_zoom_in", "graphics": [{"type": "background_card", "heading": "Life", "lines": ["It computes"]}]},
    ]
    chunks = captions.chunk_words(narration.words, STYLE)
    ass = tmp_path / "c.ass"
    ass.write_text(captions.to_ass(chunks, STYLE, (1080, 1920)))
    mix = audio.build_tracks(ctx, voice_raw=Path(narration.audio_path), out_dir=tmp_path / "a", duration=dur)["mix"]
    info = render.render_video(scenes=scenes, sources_by_id={"s1": src}, audio_mix=mix, ass_path=ass, duration=dur,
                               out_path=tmp_path / "out.mp4", work=tmp_path / "work", cfg=ctx.cfg)
    assert (info.width, info.height) == (1080, 1920)
    assert info.video_codec == "h264" and info.audio_codec == "aac" and info.pix_fmt == "yuv420p"
    assert info.fps == 30 and info.duration == pytest.approx(dur, abs=0.1)
    assert ffmpeg.decode_errors(tmp_path / "out.mp4") == []
    assert not [b for b in ffmpeg.detect_black(tmp_path / "out.mp4") if b[1] - b[0] > 0.3]
