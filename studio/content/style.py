"""Anti-slop style linter. Rules live in config/style.yaml."""
from __future__ import annotations

import re
from collections import Counter

from ..textutil import norm_words, split_sentences

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")


def _starts_with(text: str, phrases: list[str]) -> str | None:
    t = re.sub(r"^[^A-Za-z0-9]+", "", text.strip().lower()).replace("’", "'")
    return next((p for p in phrases if t.startswith(p.lower())), None)


def _contains(text: str, phrases: list[str]) -> list[str]:
    t = " " + re.sub(r"\s+", " ", text.lower().replace("’", "'")) + " "
    return [p for p in phrases if re.search(r"(?<![a-z])" + re.escape(p.lower()) + r"(?![a-z])", t)]


def opening(text: str, n: int = 5) -> str:
    return " ".join(norm_words(text)[:n])


def lint(sections: dict[str, list[str]], style: dict, *, recent_openings: list[str] | None = None) -> dict:
    """sections: {"HOOK": [sentences], ...}. Returns {"passed", "issues", "metrics"}."""
    limits = style.get("limits", {})
    all_sents = [s for sents in sections.values() for s in sents]
    text = " ".join(all_sents)
    issues: list[dict] = []

    for name, sents in sections.items():
        if sents:
            hit = _starts_with(sents[0], style.get("banned_openings", []))
            if hit:
                issues.append({"rule": "banned_opening", "section": name, "detail": hit})
    for p in _contains(text, style.get("banned_phrases", [])):
        issues.append({"rule": "banned_phrase", "detail": p})

    hype = sum(len(re.findall(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text.lower()))
               for w in style.get("hype_words", []))
    if hype > limits.get("max_hype_words_per_script", 1):
        issues.append({"rule": "hype_words", "detail": f"{hype} hype words"})
    excl = text.count("!")
    if excl > limits.get("max_exclamations_per_script", 1):
        issues.append({"rule": "exclamations", "detail": f"{excl} exclamation marks"})
    emojis = len(_EMOJI.findall(text))
    if emojis > limits.get("max_emojis_per_script", 0):
        issues.append({"rule": "emojis", "detail": f"{emojis} emojis"})

    sentences = [s for sent in all_sents for s in split_sentences(sent)]
    avg_len = sum(len(norm_words(s)) for s in sentences) / len(sentences) if sentences else 0
    if avg_len > limits.get("max_avg_sentence_words", 18):
        issues.append({"rule": "long_sentences", "detail": f"average {avg_len:.1f} words"})
    firsts = Counter(norm_words(s)[0] for s in sentences if norm_words(s))
    if sentences and len(sentences) >= 4:
        word, count = firsts.most_common(1)[0]
        if count / len(sentences) > limits.get("max_same_opening_word_ratio", 0.34):
            issues.append({"rule": "repetitive_openings", "detail": f"'{word}' starts {count} of {len(sentences)} sentences"})

    first = opening(all_sents[0]) if all_sents else ""
    if first and recent_openings and first in set(recent_openings):
        issues.append({"rule": "repeated_opening_across_videos", "detail": first})

    return {"passed": not issues, "issues": issues,
            "metrics": {"hype_words": hype, "exclamations": excl, "emojis": emojis,
                        "avg_sentence_words": round(avg_len, 1), "sentences": len(sentences), "opening": first}}


def title_issues(title: str, style: dict) -> list[str]:
    out = [f"clickbait term: {t}" for t in _contains(title, style.get("clickbait_title_terms", []))]
    out += [f"banned phrase: {p}" for p in _contains(title, style.get("banned_phrases", []))]
    if title.isupper() and len(title) > 12:
        out.append("all caps")
    if title.count("!") > 1:
        out.append("multiple exclamation marks")
    return out


def absolute_terms(text: str, style: dict) -> list[str]:
    return _contains(text, style.get("absolute_terms", []))
