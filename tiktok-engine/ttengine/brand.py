"""Brand + series identity applied to graphics, captions and end cards.

Consistency comes from palette, fonts, caption style, logo, series tag and
outro; variety comes from format, visuals and hook type per video.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from studio.media import graphics


def apply(ctx, series_id: str | None = None) -> dict:
    """Point the core graphics module at this brand's palette and fonts (process-wide)."""
    pal = ctx.palette(series_id)
    for key in ("bg_top", "bg_bottom", "accent", "text", "muted", "highlight"):
        if key in pal:
            graphics.PALETTE[key] = tuple(pal[key][:3])
    if "panel" in pal:
        graphics.PALETTE["panel"] = tuple(pal["panel"]) if len(pal["panel"]) == 4 else (*pal["panel"], 200)
    fonts = ctx.brand.get("font") or {}
    if fonts.get("bold") and Path(fonts["bold"]).exists():
        graphics.BOLD = fonts["bold"]
    if fonts.get("regular") and Path(fonts["regular"]).exists():
        graphics.REGULAR = fonts["regular"]
    return pal


def logo(ctx, out: Path, size: int = 160) -> Path:
    spec = ctx.brand.get("logo") or {}
    if spec.get("kind") == "file" and spec.get("file") and Path(spec["file"]).exists():
        img = Image.open(spec["file"]).convert("RGBA")
        img.thumbnail((size, size))
    else:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((0, 0, size - 1, size - 1), fill=(*graphics.PALETTE["accent"], 235))
        f = graphics.font(int(size * 0.42))
        text = spec.get("text") or ctx.brand.get("channel_name", "?")[:2].upper()
        w = f.getlength(text)
        d.text(((size - w) / 2, size * 0.24), text, font=f, fill=(*graphics.PALETTE["bg_top"], 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def series_tag(ctx, series_id: str | None, size=(1080, 1920)) -> Image.Image | None:
    s = ctx.series.get(series_id or "")
    if not s or s.get("intro_style") != "series_tag":
        return None
    tag = (s.get("visual_identity") or {}).get("tag") or s["name"].upper()
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = graphics.font(38)
    w = f.getlength(tag)
    x, y = graphics.SAFE_X[0], 190
    d.rounded_rectangle((x, y, x + w + 44, y + 62), radius=31, fill=(*graphics.PALETTE["accent"], 235))
    d.text((x + 22, y + 10), tag, font=f, fill=(*graphics.PALETTE["bg_top"], 255))
    return img


def question_card(ctx, question: str, size=(1080, 1920)) -> Image.Image:
    """End card: the comment prompt as a genuine open question, plus the handle."""
    img = Image.new("RGBA", size, (*graphics.PALETTE["bg_top"], 255))  # opaque: the previous visual must not show through
    heading_font, body_font = graphics.font(46), graphics.font(64)
    lines = graphics.wrap(question, body_font, graphics.SAFE_X[1] - graphics.SAFE_X[0] - 100)[:4]
    top = graphics.CARD_TOP + 40
    h = 130 + 80 * len(lines) + 60
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((graphics.SAFE_X[0], top, graphics.SAFE_X[1], top + h), radius=34,
                                            fill=graphics.PALETTE["panel"])
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.text((graphics.SAFE_X[0] + 50, top + 36), "YOUR TAKE?", font=heading_font, fill=graphics.PALETTE["accent"])
    y = top + 120
    for ln in lines:
        d.text((graphics.SAFE_X[0] + 50, y), ln, font=body_font, fill=graphics.PALETTE["text"])
        y += 80
    handle = ctx.brand.get("handle")
    if handle:
        hf = graphics.font(38, bold=False)
        d.text((graphics.SAFE_X[0] + 50, top + h + 24), handle, font=hf, fill=graphics.PALETTE["muted"])
    return img
