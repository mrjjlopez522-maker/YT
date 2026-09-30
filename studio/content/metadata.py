"""Titles, descriptions, keywords, hashtags and thumbnail concepts.

Titles must be accurate (their key terms appear in the script or research),
concise, curiosity-driven without clickbait, and different from past titles.
Descriptions always carry sources and required footage attributions.
"""
from __future__ import annotations

import re
from collections import Counter

import yaml

from ..sources.rights import attribution_line
from ..textutil import STOPWORDS, content_words, norm_words, split_sentences, text_similarity, word_count
from . import style as style_mod

MAX_TITLE = 70
MAX_DESCRIPTION = 4800  # YouTube allows 5000; leave headroom


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().strip('"')


def title_score(title: str, script_text: str, topic: str, past_titles: list[str], style_cfg: dict) -> tuple[float, dict]:
    from .factcheck import stems
    known = stems(script_text) | stems(topic)
    key = [w for w in content_words(title) if len(w) > 3]
    from .factcheck import stem
    accuracy = sum(1 for w in key if stem(w) in known) / len(key) if key else 0.0
    n = len(title)
    words = set(norm_words(title))
    crit = {
        "length": 1.0 if 25 <= n <= 55 else 0.6 if n <= MAX_TITLE else 0.0,
        "accuracy": round(accuracy, 3),
        "topic_named": 1.0 if set(content_words(topic)) & set(content_words(title)) else 0.4,
        "novelty": round(1 - max([text_similarity(title, p) for p in past_titles] or [0.0]), 3),
        "self_contained": 0.0 if words & {"this", "these", "that", "here"} else 1.0,
        "clean": 0.0 if style_mod.title_issues(title, style_cfg) or title.endswith(("…", "...")) else 1.0,
    }
    score = 0.0 if crit["clean"] == 0 or crit["accuracy"] < 0.6 or crit["length"] == 0 else \
        round(crit["length"] + 2 * crit["accuracy"] + crit["topic_named"] + crit["novelty"] + crit["self_contained"], 3)
    return score, crit


def _clause(text: str, max_len: int) -> str:
    """First complete clause of a sentence if it fits; never a mid-clause cut."""
    first = split_sentences(text)[0] if text else ""
    clause = re.split(r"[,;:—]", first)[0].strip().rstrip(".")
    return clause if 0 < len(clause) <= max_len else ""


LOW_INFO = frozenset("""every first once actually entirely really still later often never always anyone
something someone thing things another across around within without their there where which while""".split())


def keywords(script_text: str, topic: str, facts_text: str, n: int = 10) -> list[str]:
    words = [w for w in content_words(script_text + " " + facts_text)
             if len(w) > 3 and not w.isdigit() and w not in LOW_INFO]
    counts = Counter(words)
    toks = norm_words(script_text)
    bigrams = Counter(f"{a} {b}" for a, b in zip(toks, toks[1:])
                      if a not in STOPWORDS and b not in STOPWORDS and len(a) > 2 and len(b) > 2)
    out = [topic.lower()]
    for bg, c in bigrams.most_common(10):
        if c >= 2 and bg not in out:
            out.append(bg)
    for w, _ in counts.most_common(60):
        if len(out) >= n:
            break
        if w not in out and not any(w in o.split() for o in out):
            out.append(w)
    return out[:n]


def _hashtag(text: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", re.sub(r"['’]", "", text))
    return "#" + "".join(p[:1].upper() + p[1:] for p in parts)[:30] if parts else ""


def hashtag_sets(topic: str, category: str | None, kws: list[str]) -> list[list[str]]:
    base = _hashtag(topic)
    cat = _hashtag(category or "")
    extra = [_hashtag(k) for k in kws[1:] if _hashtag(k) and _hashtag(k) != base][:6]
    sets = [
        [base, cat, "#Shorts"],
        [base, *extra[:2]],
        [cat, *extra[2:4]],
        [base, "#Explained", extra[4] if len(extra) > 4 else cat],
        [base, cat, extra[0] if extra else "#Learn"],
    ]
    out = []
    for s in sets:
        tags = [t for t in dict.fromkeys(s) if t and t != "#"]
        if tags and tags not in out:
            out.append(tags[:3])
    while len(out) < 5:
        out.append([base, "#Shorts"][: 2])
    return out[:5]


def build_metadata(*, topic: dict, script: dict, facts: list[dict], sources: list[dict], licenses: dict,
                   past_titles: list[str], style_cfg: dict, duration: float, synthetic_voice: bool) -> dict:
    sections = {s["name"]: [x["text"] for x in s["sentences"]] for s in script["sections_json"]}
    text = script["full_text"]
    hook = script["selected_hook"]
    blueprint = script["blueprint_json"]
    payoff = (sections.get("PAYOFF") or [""])[-1]
    name = topic["topic"]
    extras = (script.get("style_report_json") or {}).get("extras") or {}

    # -- titles
    candidates = [_clean(t) for t in extras.get("titles", [])]
    candidates += [
        _clean(hook) if len(hook) <= MAX_TITLE and not hook.endswith("?") else "",
        _clean(blueprint.get("viewer_question", "")),
        f"{name}, explained in {int(round(duration))} seconds",
        f"How {name} works",
        f"The story behind {name}",
        f"{name}: {_clause(payoff, MAX_TITLE - len(name) - 2)}" if _clause(payoff, MAX_TITLE - len(name) - 2) else "",
        f"{name}: {blueprint['format'].replace('_', ' ').lower()}",
    ]
    scored = []
    for t in dict.fromkeys(c for c in candidates if c):
        s, crit = title_score(t, text, name, past_titles, style_cfg)
        if s > 0:
            scored.append({"title": t, "score": s, "criteria": crit})
    scored.sort(key=lambda x: x["score"], reverse=True)
    titles = scored[:5]

    # -- sources + attributions (always included)
    used_ids = {fid for sec in script["sections_json"] for x in sec["sentences"] for fid in x.get("fact_ids", [])}
    source_lines, seen = [], set()
    for f in facts:
        if used_ids and f["fact_id"] not in used_ids:
            continue
        for title, url in [(f.get("source_title"), f.get("source_url")),
                           *[(e.get("title"), e.get("url")) for e in (f.get("extra_sources_json") or [])]]:
            key = url or title
            if key and key not in seen:
                seen.add(key)
                source_lines.append(f"- {title or ''} {url or ''}".rstrip())
    credit_lines = []
    for s in sources:
        lic = licenses.get(s["source_id"]) or {}
        if lic.get("attribution_required"):
            credit_lines.append("- " + attribution_line(lic["license_type"], s.get("creator"), s.get("title"),
                                                        lic.get("attribution_text")))
    tail = "\n\nSources:\n" + "\n".join(source_lines)
    if credit_lines:
        tail += "\n\nFootage credits:\n" + "\n".join(credit_lines)
    if synthetic_voice:
        tail += "\n\nNarration uses a synthetic (text-to-speech) voice."

    bodies = [_clean(d) for d in extras.get("descriptions", []) if d]
    first = split_sentences(" ".join(sections.get("SETUP", [])))
    bodies += [
        " ".join(filter(None, [hook, first[0] if first else "", payoff])),
        f"{blueprint.get('viewer_question', '')} {payoff}".strip(),
        f"A short {blueprint['format'].replace('_', ' ').lower()} on {name}. {payoff}".strip(),
    ]
    descriptions = []
    for b in dict.fromkeys(bodies):
        if b and not style_mod.title_issues(b, style_cfg):
            descriptions.append((b + tail)[:MAX_DESCRIPTION])
        if len(descriptions) == 3:
            break

    kws = keywords(text, name, " ".join(f["text"] for f in facts))
    tags = hashtag_sets(name, topic.get("category"), kws)

    short = next((t["title"] for t in titles if word_count(t["title"]) <= 6), name)
    concepts = [
        {"concept": "strongest_frame", "text": " ".join(short.split()[:4]).upper(),
         "visual": "best visual moment from the approved footage, with a bold 3-4 word label"},
        {"concept": "key_number_or_date", "text": next((w for w in norm_words(text) if w.isdigit() and len(w) == 4),
                                                       name.split()[0]).upper(),
         "visual": "large date/number over a darkened frame"},
        {"concept": "question", "text": (blueprint.get("viewer_question") or name)[:40],
         "visual": "clean graphic card with the viewer question"},
    ]
    return {
        "titles": titles, "descriptions": descriptions, "keywords": kws, "hashtag_sets": tags,
        "thumbnail_concepts": concepts,
        "selected_title": titles[0]["title"] if titles else name[:MAX_TITLE],
        "selected_description": descriptions[0] if descriptions else tail.strip(),
    }


def load_style(ctx) -> dict:
    return yaml.safe_load(ctx.cfg.config_file(ctx.cfg.get("content.style_file")).read_text(encoding="utf-8"))
