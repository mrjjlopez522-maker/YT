"""Text helpers: IDs, slugs, tokenisation, similarity measures.

Pure functions with no external dependencies so they are easy to test and reuse.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import unicodedata
import uuid
from collections import Counter

STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have he her his how i if in into is it its
just me more most my no not of on or our out over she so some than that the their them then there these they this
those to too up us was we were what when where which while who whom why will with would you your about after again
all also any because before being between both down during each few further here itself only other own same should
such through under until very s t don now one two
""".split())

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?(?:[.,][0-9]+)*")
_SENT_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9])")
_NUM_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}


# -- ids -----------------------------------------------------------------
def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0] or text[:max_len]
    return text or "untitled"


# -- tokenisation --------------------------------------------------------
def words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def norm_words(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in words(text)]


def content_words(text: str) -> list[str]:
    return [w for w in norm_words(text) if w not in STOPWORDS and len(w) > 1]


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


def numbers_in(text: str) -> set[str]:
    """Numbers as normalised strings ('1,000' -> '1000'); includes simple number words."""
    found = {n.replace(",", "") for n in _NUM_RE.findall(text or "")}
    for w in norm_words(text):
        if w in _WORD_NUMBERS:
            found.add(str(_WORD_NUMBERS[w]))
    return found


def capitalized_terms(text: str) -> set[str]:
    """Rough named-entity proxy: capitalised words not at sentence start."""
    out = set()
    for sent in split_sentences(text):
        toks = words(sent)
        for i, tok in enumerate(toks):
            if i > 0 and tok[:1].isupper() and tok.lower() not in STOPWORDS:
                out.add(tok.lower())
    return out


def word_count(text: str) -> int:
    return len(words(text))


# -- similarity ----------------------------------------------------------
def shingles(tokens: list[str], n: int = 3) -> set[tuple[str, ...]]:
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def cosine_tf(a_tokens: list[str], b_tokens: list[str]) -> float:
    ca, cb = Counter(a_tokens), Counter(b_tokens)
    if not ca or not cb:
        return 0.0
    dot = sum(ca[t] * cb[t] for t in ca.keys() & cb.keys())
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb)


def text_similarity(a: str, b: str) -> float:
    """Blend of shingle overlap (phrasing) and content-word cosine (subject)."""
    ta, tb = norm_words(a), norm_words(b)
    sh = jaccard(shingles(ta, 3), shingles(tb, 3))
    cos = cosine_tf(content_words(a), content_words(b))
    return round(0.5 * sh + 0.5 * cos, 4)


def longest_common_run(a: str, b: str) -> int:
    """Length in words of the longest shared contiguous word sequence (verbatim-copy detector)."""
    ta, tb = norm_words(a), norm_words(b)
    if not ta or not tb:
        return 0
    best = 0
    prev = [0] * (len(tb) + 1)
    for i in range(1, len(ta) + 1):
        cur = [0] * (len(tb) + 1)
        ai = ta[i - 1]
        for j in range(1, len(tb) + 1):
            if ai == tb[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def estimate_syllables(word: str) -> int:
    w = word.lower()
    if w.isdigit():
        return max(1, len(w))  # rough: digits read as words
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith("le"):
        n -= 1
    return max(1, n)
