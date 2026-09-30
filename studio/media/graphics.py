"""Original graphics rendered with Pillow as full-frame RGBA overlays (or RGB cards).

Layout respects the Shorts UI: top ~250px (search/camera icons), bottom ~20%
(title/channel), right-hand button column. Cards sit in the upper-middle band;
captions own the lower-middle band.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PALETTE = {"bg_top": (11, 16, 32), "bg_bottom": (27, 58, 92), "accent": (60, 240, 140), "panel": (8, 12, 24, 200),
           "text": (255, 255, 255), "muted": (190, 200, 215), "highlight": (255, 210, 63)}
SAFE_X = (90, 990)
CARD_TOP = 300


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(BOLD if bold else REGULAR, size)
    except OSError:
        return ImageFont.load_default(size)


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if fnt.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _canvas(size) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _panel(img: Image.Image, box, radius=28, fill=PALETTE["panel"]) -> None:
    layer = _canvas(img.size)
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=fill)
    img.alpha_composite(layer)


def title_card(text: str, size=(1080, 1920), *, max_lines: int = 3) -> Image.Image:
    img = _canvas(size)
    fnt = font(76)
    width = SAFE_X[1] - SAFE_X[0] - 80
    lines = wrap(text, fnt, width)[:max_lines]
    line_h = 92
    h = line_h * len(lines) + 70
    _panel(img, (SAFE_X[0], CARD_TOP, SAFE_X[1], CARD_TOP + h))
    d = ImageDraw.Draw(img)
    d.rectangle((SAFE_X[0] + 34, CARD_TOP + 30, SAFE_X[0] + 44, CARD_TOP + h - 30), fill=PALETTE["accent"])
    for i, ln in enumerate(lines):
        d.text((SAFE_X[0] + 70, CARD_TOP + 34 + i * line_h), ln, font=fnt, fill=PALETTE["text"])
    return img


def fact_card(heading: str, lines: list[str], size=(1080, 1920)) -> Image.Image:
    img = _canvas(size)
    hf, bf = font(58), font(46, bold=False)
    width = SAFE_X[1] - SAFE_X[0] - 100
    body = [w for ln in lines for w in wrap(ln, bf, width - 40)][:7]
    h = 110 + 60 * len(body) + 40
    _panel(img, (SAFE_X[0], CARD_TOP, SAFE_X[1], CARD_TOP + h))
    d = ImageDraw.Draw(img)
    d.text((SAFE_X[0] + 50, CARD_TOP + 34), heading, font=hf, fill=PALETTE["accent"])
    y = CARD_TOP + 120
    for ln in body:
        d.text((SAFE_X[0] + 60, y), ln, font=bf, fill=PALETTE["text"])
        y += 60
    return img


def timeline(years: list[str], active: int, size=(1080, 1920), label: str | None = None) -> Image.Image:
    img = _canvas(size)
    n = max(1, len(years))
    top, h = CARD_TOP, 230 if label else 190
    _panel(img, (SAFE_X[0], top, SAFE_X[1], top + h))
    d = ImageDraw.Draw(img)
    x0, x1, y = SAFE_X[0] + 80, SAFE_X[1] - 80, top + 95
    d.line((x0, y, x1, y), fill=PALETTE["muted"], width=6)
    f = font(44)
    for i, yr in enumerate(years):
        x = x0 + (x1 - x0) * (i / (n - 1) if n > 1 else 0.5)
        on = i == active
        r = 20 if on else 13
        d.ellipse((x - r, y - r, x + r, y + r), fill=PALETTE["accent"] if on else PALETTE["muted"])
        w = f.getlength(yr)
        d.text((x - w / 2, y + 30), yr, font=f, fill=PALETTE["text"] if on else PALETTE["muted"])
    if label:
        lf = font(36, bold=False)
        d.text((SAFE_X[0] + 50, top + 22), label, font=lf, fill=PALETTE["muted"])
    return img


def highlight_box(box: tuple[int, int, int, int], size=(1080, 1920), *, label: str | None = None) -> Image.Image:
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=18, outline=PALETTE["highlight"], width=10)
    if label:
        f = font(44)
        x, y = box[0], max(CARD_TOP, box[1] - 80)
        tw = f.getlength(label)
        d.rounded_rectangle((x, y, x + tw + 40, y + 64), radius=14, fill=(0, 0, 0, 190))
        d.text((x + 20, y + 8), label, font=f, fill=PALETTE["highlight"])
    return img


def arrow(start: tuple[int, int], end: tuple[int, int], size=(1080, 1920)) -> Image.Image:
    import math
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    d.line((*start, *end), fill=PALETTE["highlight"], width=12)
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    for s in (-0.5, 0.5):
        d.line((*end, end[0] - 50 * math.cos(ang + s), end[1] - 50 * math.sin(ang + s)), fill=PALETTE["highlight"], width=12)
    return img


def attribution(text: str, size=(1080, 1920)) -> Image.Image:
    img = _canvas(size)
    f = font(30, bold=False)
    lines = wrap(text, f, 700)[:2]
    y = 250
    for ln in lines:
        w = f.getlength(ln)
        _panel(img, (SAFE_X[0] - 20, y - 6, SAFE_X[0] + w + 20, y + 40), radius=10, fill=(0, 0, 0, 150))
        ImageDraw.Draw(img).text((SAFE_X[0], y), ln, font=f, fill=PALETTE["muted"])
        y += 48
    return img


def gradient(size=(1080, 1920)) -> Image.Image:
    w, h = size
    top, bot = PALETTE["bg_top"], PALETTE["bg_bottom"]
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for yy in range(h):
        t = yy / (h - 1)
        px.line((0, yy, w, yy), fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img


def graphic_background(heading: str, lines: list[str], size=(1080, 1920)) -> Image.Image:
    """A full original-graphics scene: gradient + grid motif + text card."""
    img = gradient(size).convert("RGBA")
    d = ImageDraw.Draw(img)
    for x in range(0, size[0], 60):
        d.line((x, 0, x, size[1]), fill=(255, 255, 255, 14))
    for y in range(0, size[1], 60):
        d.line((0, y, size[0], y), fill=(255, 255, 255, 14))
    img.alpha_composite(fact_card(heading, lines, size))
    return img.convert("RGB")


def progress_bar(width: int = 1080, height: int = 10) -> Image.Image:
    return Image.new("RGBA", (width, height), (*PALETTE["accent"], 230))


def thumbnail(text: str, frame: Path | None, out: Path, size=(1080, 1920)) -> Path:
    if frame and Path(frame).exists():
        base = Image.open(frame).convert("RGB").resize(size)
        base = Image.blend(base, Image.new("RGB", size, (0, 0, 0)), 0.35)
    else:
        base = gradient(size)
    img = base.convert("RGBA")
    size_px = 128
    while True:  # shrink until the whole text fits in four lines — never cut words off
        f = font(size_px)
        lines = wrap(text.upper(), f, SAFE_X[1] - SAFE_X[0])
        if len(lines) <= 4 or size_px <= 56:
            break
        size_px -= 8
    step = int(size_px * 1.17)
    y = 560
    shadow = _canvas(size)
    ds = ImageDraw.Draw(shadow)
    for ln in lines:
        w = f.getlength(ln)
        ds.text(((size[0] - w) / 2 + 6, y + 6), ln, font=f, fill=(0, 0, 0, 220))
        y += step
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(img)
    y = 560
    for ln in lines:
        w = f.getlength(ln)
        d.text(((size[0] - w) / 2, y), ln, font=f, fill=PALETTE["highlight"])
        y += step
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out


def save(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
