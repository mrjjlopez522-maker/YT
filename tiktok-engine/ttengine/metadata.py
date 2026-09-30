"""TikTok post metadata: 5 captions, 3 descriptions, 10 keywords, 5 hashtag sets.

Captions read like a person wrote them, stay accurate to the script, avoid
keyword stuffing and bait, and disclose synthetic narration when configured.
Links are not clickable in TikTok captions, so sources are named briefly and
kept in full in the audit trail and research packet.
"""
from __future__ import annotations

from studio.content.metadata import hashtag_sets, keywords, title_score
from studio.content.style import title_issues
from studio.textutil import split_sentences
from .script import bait_issues, load_style

MAX_CAPTION = 150        # the visible part before "more"; the API allows much longer text
DISCLOSURE = "Narrated with a synthetic (AI) voice."


def short_source(title: str) -> str:
    """'Mandelbrot, B. (1967). How Long Is ...' -> 'Mandelbrot 1967'; 'Mandelbrot set (Wikipedia)' -> 'Mandelbrot set'."""
    import re
    m = re.match(r"^([A-Z][\w'-]+),.*?\((\d{4})\)", title or "")
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return (title or "").split(" (")[0]


def _clause(text: str, n: int = 90) -> str:
    first = split_sentences(text)[0] if text else ""
    return first if len(first) <= n else first.split(",")[0]


def build(ctx, *, topic: dict, script: dict, packet: dict, comment_prompts: list[dict]) -> dict:
    style = load_style(ctx)
    sections = {s["name"]: [x["text"] for x in s["sentences"]] for s in script["sections_json"]}
    hook = script["selected_hook"]
    payoff = " ".join(sections.get("PAYOFF", []))
    context = " ".join(sections.get("CONTEXT", []))
    name = topic["topic"]
    blueprint = script.get("blueprint_json") or {}
    cands = [
        hook,
        *(packet.get("caption_ideas") or []),          # optional, written by the researcher
        _clause(context),
        f"{name}: {_clause(payoff, 100).rstrip('.')}",
        blueprint.get("viewer_question") or "",
        f"{name}, explained",
        _clause(payoff, 120),
    ]
    captions = []
    for c in dict.fromkeys(x.strip() for x in cands if x and x.strip()):
        if len(c) > MAX_CAPTION or title_issues(c, style) or bait_issues([c], style):
            continue
        score, crit = title_score(c if len(c) <= 70 else c[:70], script["full_text"], name, [], style)
        if score > 0 or c == hook:
            captions.append({"caption": c, "score": score, "criteria": crit})
    captions.sort(key=lambda x: (x["caption"] != hook, -x["score"]))
    captions = captions[:5]

    src_names = []
    for s in packet.get("sources", []):
        title = short_source(s.get("title") or "")
        if title and title not in src_names:
            src_names.append(title if len(title) < 60 else title[:57] + "…")
    sources_line = "Sources: " + "; ".join(src_names[:4]) + (" (full list on request)" if len(src_names) > 4 else "")
    disclose = bool(ctx.cfg.get("publishing.disclose_synthetic_voice"))
    tail = f"\n\n{sources_line}" + (f"\n{DISCLOSURE}" if disclose else "")
    bodies = [f"{hook} {_clause(context)}", _clause(payoff, 140), f"{name}, explained with sources."]
    descriptions = [b.strip() + tail for b in dict.fromkeys(bodies) if b.strip() and not bait_issues([b], style)][:3]

    kws = keywords(script["full_text"], name, " ".join(f["text"] for f in packet.get("important_facts", [])))
    tags = [[t for t in s if t != "#Shorts"] or s for s in hashtag_sets(name, topic.get("category"), kws)]
    series = ctx.series.get(packet.get("series") or "")
    if series:
        series_tag = "#" + "".join(w.capitalize() for w in series["name"].split())
        tags = [[series_tag, *t][:4] for t in tags]
    selected = captions[0]["caption"] if captions else hook
    return {"captions": captions, "descriptions": descriptions, "keywords": kws, "hashtag_sets": tags,
            "comment_prompts": comment_prompts, "selected_caption": selected,
            "selected_description": descriptions[0] if descriptions else selected + tail,
            "post_text": f"{selected} {' '.join(tags[0])}".strip() + (f"\n{DISCLOSURE}" if disclose else ""),
            "disclosure": DISCLOSURE if disclose else None}
