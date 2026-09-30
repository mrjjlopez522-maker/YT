"""Caption engine: word timings -> readable chunks -> ASS (burned in) + SRT (sidecar).

Styles live in config/caption_styles.yaml, not here. Captions are built from
the approved script text, so spelling matches the script exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..errors import ValidationError

_BREAK_AFTER = re.compile(r"[.!?;:,—–]$")


@dataclass
class Chunk:
    text: str
    start: float
    end: float
    words: list[dict] = field(default_factory=list)  # {word, start, end}


def chunk_words(words: list, style: dict) -> list[Chunk]:
    max_words = int(style.get("max_words_per_chunk", 3))
    max_chars = int(style.get("max_chars_per_chunk", 18))
    min_dur = float(style.get("min_chunk_seconds", 0.35))
    chunks: list[Chunk] = []
    cur: list = []

    def flush():
        if cur:
            chunks.append(Chunk(" ".join(w.word for w in cur), cur[0].start, cur[-1].end,
                                [{"word": w.word, "start": w.start, "end": w.end} for w in cur]))
            cur.clear()

    for w in words:
        prospective = " ".join([*(x.word for x in cur), w.word])
        if cur and (len(cur) >= max_words or len(prospective) > max_chars or w.section != cur[-1].section):
            flush()
        cur.append(w)
        if _BREAK_AFTER.search(w.word):
            flush()
    flush()
    # enforce a minimum on-screen time without overlapping the next chunk
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1].start if i + 1 < len(chunks) else None
        if c.end - c.start < min_dur:
            c.end = c.start + min_dur if nxt is None else min(c.start + min_dur, nxt)
        if nxt is not None and c.end > nxt:
            c.end = nxt
        # bridge tiny gaps so captions don't flicker between words of one breath
        if nxt is not None and 0 < nxt - c.end < 0.25:
            c.end = nxt
    return chunks


def validate(chunks: list[Chunk], words: list, audio_duration: float) -> list[str]:
    problems = []
    for i, c in enumerate(chunks):
        if c.end <= c.start:
            problems.append(f"chunk {i} has non-positive duration")
        if c.end > audio_duration + 0.05:
            problems.append(f"chunk {i} ends after the audio ({c.end:.2f}s > {audio_duration:.2f}s)")
        if i and c.start < chunks[i - 1].end - 1e-6:
            problems.append(f"chunk {i} overlaps the previous chunk")
    caption_words = [w["word"] for c in chunks for w in c.words]
    if caption_words != [w.word for w in words]:
        problems.append("caption words do not match narration words")
    for w in words:
        if w.end < w.start:
            problems.append(f"word {w.word!r} ends before it starts")
    return problems


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = h[6:8] if len(h) == 8 else "FF"
    alpha = 255 - int(a, 16)  # ASS alpha: 00 opaque, FF transparent
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def to_ass(chunks: list[Chunk], style: dict, resolution: tuple[int, int],
           emphasis_words: set[str] | None = None) -> str:
    """word_highlight: karaoke-style active word. emphasis: 'keywords' colours only the given
    important words (numbers, names, key terms), at most one per chunk."""
    w, h = resolution
    upper = bool(style.get("uppercase"))
    box = bool(style.get("box"))
    primary = _ass_color(style.get("primary_color", "#FFFFFF"))
    outline = _ass_color(style.get("outline_color", "#000000"))
    back = _ass_color(style.get("box_color", "#000000A0")) if box else "&H80000000"
    hl = _ass_color(style.get("highlight_color", "#FFD23F"))
    border_style = 3 if box else 1
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Caption,{style.get('font', 'DejaVu Sans')},{style.get('font_size', 80)},{primary},{hl},{outline},"
        f"{back},{-1 if style.get('bold', True) else 0},0,0,0,100,100,0,0,{border_style},"
        f"{style.get('outline_width', 5) if not box else 14},{style.get('shadow', 0)},2,{style.get('margin_lr', 100)},"
        f"{style.get('margin_lr', 100)},{style.get('margin_v', 600)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    emph = {w.lower() for w in (emphasis_words or set())}
    for c in chunks:
        ws = [x["word"].upper() if upper else x["word"] for x in c.words]
        if style.get("emphasis") == "keywords":
            hit = next((j for j, x in enumerate(c.words) if re.sub(r"[^\w']", "", x["word"]).lower() in emph), None)
            text = " ".join(("{\\c" + hl + "}" + _esc(t) + "{\\r}") if j == hit else _esc(t) for j, t in enumerate(ws))
            lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Caption,,0,0,0,,{text}")
        elif style.get("word_highlight") and len(ws) > 1:
            for i, word in enumerate(c.words):
                start = c.start if i == 0 else word["start"]
                end = c.words[i + 1]["start"] if i + 1 < len(c.words) else c.end
                if end <= start:
                    continue
                text = " ".join(("{\\c" + hl + "}" + _esc(t) + "{\\r}") if j == i else _esc(t) for j, t in enumerate(ws))
                lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{text}")
        else:
            lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Caption,,0,0,0,,{_esc(' '.join(ws))}")
    return "\n".join(lines) + "\n"


def to_srt(chunks: list[Chunk]) -> str:
    def ts(t):
        ms = int(round(max(0.0, t) * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return "\n".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n" for i, c in enumerate(chunks, 1))


def load_style(ctx, name: str | None = None) -> dict:
    styles = ctx.cfg.load_yaml("captions.styles_file")
    key = name or ctx.cfg.get("captions.style")
    if key not in styles:
        raise ValidationError(f"Caption style {key!r} not found in {ctx.cfg.get('captions.styles_file')}",
                              hint=f"available: {', '.join(styles)}")
    return {"name": key, **styles[key]}
