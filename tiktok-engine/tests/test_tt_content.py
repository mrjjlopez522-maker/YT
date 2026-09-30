"""Script engine, alignment, original visuals, sound and metadata."""
import numpy as np

from studio.media.tts import EspeakNGProvider
from ttengine import align, metadata, script, sound, visuals


def test_hook_types_are_typed_and_known(researched):
    ctx, tid, pk = researched
    from studio.research.topic_research import load_facts
    hooks = script.typed_hooks([f for f in load_facts(ctx, tid) if f.get("own_words")], pk)
    types = {t for _, t in hooks}
    assert types <= set(script.HOOK_TYPES)
    assert {"QUESTION", "UNEXPECTED_FACT", "VISUAL_HOOK"} <= types


def test_bait_and_fake_urgency_detected(ctx):
    style = script.load_style(ctx)
    assert script.bait_issues(["Follow for part 2!"], style)
    assert script.bait_issues(["Watch this right now"], style)
    assert not script.bait_issues(["Which shape surprised you most?"], style)


def test_promise_kept_requires_the_payoff_to_answer():
    sections = [{"name": "HOOK", "sentences": [{"text": "Why is the coastline infinite?"}]},
                {"name": "DEVELOPMENT", "sentences": [{"text": "Shorter rulers trace more bends."}]},
                {"name": "PAYOFF", "sentences": [{"text": "So the measured coastline keeps growing."}]}]
    assert script.promise_kept("Why is the coastline infinite?", sections)["kept"]
    assert not script.promise_kept("What do pandas eat?", sections)["kept"]


def test_script_has_sections_passes_factcheck_and_no_bait(researched):
    ctx, tid, _ = researched
    s = script.generate(ctx, tid, format_id="unexpected_fact_reveal")
    names = [sec["name"] for sec in s["sections_json"]]
    assert names[0] == "HOOK" and "PAYOFF" in names and "CONTEXT" in names
    assert s["factcheck_status"] == "PASSED"
    bp = s["blueprint_json"]
    assert bp["hook_type"] in script.HOOK_TYPES and bp["promise"]["kept"]
    text = " ".join(x["text"] for sec in s["sections_json"] for x in sec["sentences"])
    assert not script.bait_issues([text], script.load_style(ctx))
    claims = ctx.db.select("claims", {"script_id": s["script_id"]})
    assert claims and all(c["status"] == "VERIFIED" and c["source"] for c in claims)
    for field in ("claim_id", "claim", "source", "source_url", "confidence", "status"):
        assert field in claims[0]


def test_comment_prompts_are_questions_without_bait(researched):
    ctx, _, pk = researched
    prompts = script.comment_prompts(ctx, pk, ctx.formats["unexpected_fact_reveal"])
    assert prompts and all(p["text"].endswith("?") for p in prompts)
    assert not script.bait_issues([p["text"] for p in prompts], script.load_style(ctx))


def test_forced_alignment_recovers_word_times():
    """Align espeak at one rate to espeak at another; the target's own timings are ground truth."""
    tts = EspeakNGProvider("en-us")
    text = "The edge of the Mandelbrot set never becomes smooth, however far you zoom."
    ref = tts.synthesize(text, wpm=175, pitch=50)
    tgt = tts.synthesize(text, wpm=135, pitch=50)
    got = align.align(ref.samples, ref.sample_rate, [t for _, t in ref.events], tgt.samples, tgt.sample_rate)
    truth = [t for _, t in tgt.events]
    err = np.abs(np.array(got) - np.array(truth))
    assert np.median(err) < 0.06, err
    assert got == sorted(got)


def test_generated_visual_is_registered_cc0(ctx):
    src = visuals.generate(ctx, "equation_card", {}, 1.0, topic_id=None, tags=["test"])
    assert src["platform"] == "generated" and src["status"] == "INGESTED"
    lic = ctx.db.select("licenses", {"source_id": src["source_id"]})[0]
    assert lic["license_type"] == "CC0-1.0" and lic["verification_status"] == "VERIFIED"
    again = visuals.generate(ctx, "equation_card", {}, 1.0, topic_id=None, tags=["test"])
    assert again["source_id"] == src["source_id"]  # cached, not duplicated


def test_original_music_bed_and_sfx(ctx):
    bed = sound.music_bed(ctx, 4.0)
    whoosh = sound.transition_sfx(ctx)
    for s in (bed, whoosh):
        assert s["platform"] == "generated"
        assert ctx.db.select("licenses", {"source_id": s["source_id"]})[0]["license_type"] == "CC0-1.0"


def test_metadata_counts_and_disclosure(researched):
    ctx, tid, pk = researched
    s = script.generate(ctx, tid, format_id="unexpected_fact_reveal")
    md = metadata.build(ctx, topic=ctx.db.require("topics", tid), script=ctx.db.require("scripts", s["script_id"]),
                        packet=pk, comment_prompts=script.comment_prompts(ctx, pk, ctx.formats["unexpected_fact_reveal"]))
    assert len(md["captions"]) == 5 and len(md["descriptions"]) == 3
    assert len(md["keywords"]) == 10 and len(md["hashtag_sets"]) == 5
    assert md["disclosure"] and md["disclosure"] in md["post_text"]
    assert metadata.short_source("The Fractal Geometry of Nature — Benoit Mandelbrot (1982)")
