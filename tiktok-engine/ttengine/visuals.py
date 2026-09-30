"""Original visual generators.

Each generator renders an MP4 we made ourselves (procedural graphics, maths
visualisations, animated text) and registers it as a *source* with a
self-generated CC0 rights record whose evidence holds the generator name and
parameters. So every frame of a video traces to a rights record, and "what
original material was added" is answerable from the database.

Generators: mandelbrot_zoom, iteration_chart, equation_card, coastline, timeline,
kinetic_text, space_filling_curve, life.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from studio.errors import RenderError, ValidationError
from studio.logging_setup import get_logger
from studio.media import ffmpeg, graphics
from studio.sources import discovery, ingest
from studio.sources.providers import SourceCandidate
from studio.sources.rights import LicenseInfo
from studio.textutil import today

log = get_logger("studio.render")
W, H, FPS = 1080, 1920, 30
GENERATOR_VERSION = 2          # bump when a generator's look changes (invalidates cached clips)
CONTENT_TOP, CONTENT_BOTTOM = 300, 1080   # captions own ~1100-1300; the TikTok UI owns the bottom
MANDELBROT_PRESETS = {
    # well-known coordinates on the boundary of the set
    "seahorse": {"x": -0.743643887037151, "y": 0.131825904205330, "start_scale": 3.0, "end_scale": 0.0006},
    "overview": {"x": -0.60, "y": 0.0, "start_scale": 3.2, "end_scale": 2.4},
    "minibrot": {"x": -1.7685736562, "y": 0.0017642, "start_scale": 0.05, "end_scale": 0.00004},
    "elephant": {"x": 0.2549870375, "y": -0.0005316, "start_scale": 0.6, "end_scale": 0.00008},
}


# -- frame writer ---------------------------------------------------------------------
class FrameWriter:
    """Pipe RGB frames into ffmpeg (H.264, yuv420p)."""

    def __init__(self, out: Path, fps: int = FPS, size=(W, H)):
        self.out, self.size = Path(out), size
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", str(self.out)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, img: Image.Image) -> None:
        self.proc.stdin.write(img.convert("RGB").tobytes())

    def close(self) -> Path:
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait(timeout=600) != 0:
            raise RenderError(f"frame encoding failed: {err[-300:]}")
        return self.out


def _bg() -> Image.Image:
    img = graphics.gradient((W, H)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for x in range(0, W, 60):
        d.line((x, 0, x, H), fill=(255, 255, 255, 12))
    for y in range(0, H, 60):
        d.line((0, y, W, y), fill=(255, 255, 255, 12))
    return img


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# -- generators --------------------------------------------------------------------------
def mandelbrot_zoom(out: Path, duration: float, preset: str = "seahorse", maxiter: int = 700,
                    colormap: str = "viridis", **_) -> Path:
    p = MANDELBROT_PRESETS.get(preset)
    if not p:
        raise ValidationError(f"unknown mandelbrot preset {preset!r}")
    # render at half resolution (it is computed per pixel), then scale smoothly to 1080x1920
    src = (f"mandelbrot=size=540x960:rate={FPS}:maxiter={maxiter}:start_x={p['x']}:start_y={p['y']}:"
           f"start_scale={p['start_scale']}:end_scale={p['end_scale']}:end_pts={duration * FPS:.0f}:"
           "outer=normalized_iteration_count:inner=period")
    ffmpeg.ffmpeg(["-f", "lavfi", "-i", src, "-t", f"{duration:.3f}",
                   "-vf", f"format=gray,format=yuv444p,pseudocolor=preset={colormap},"
                          f"scale={W}:{H}:flags=lanczos,format=yuv420p",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)], what="gen-mandelbrot", timeout=1800)
    return out


def iteration_chart(out: Path, duration: float, **_) -> Path:
    """z -> z^2 + c from z = 0, for two constants: one stays small (inside), one explodes (outside)."""
    series = {"c = -1": [0.0], "c = 1": [0.0]}
    for label, c in (("c = -1", -1.0), ("c = 1", 1.0)):
        z = 0.0
        for _ in range(5):
            z = z * z + c
            series[label].append(z)
    fw = FrameWriter(out)
    n = int(duration * FPS)
    title_f, lab_f, val_f = graphics.font(58), graphics.font(44), graphics.font(34, bold=False)
    for k in range(n):
        t = k / max(1, n - 1)
        img = _bg()
        d = ImageDraw.Draw(img)
        d.text((90, CONTENT_TOP), "Start at 0. Square it, add c. Repeat.", font=lab_f, fill=graphics.PALETTE["muted"])
        for row, (label, vals) in enumerate(series.items()):
            top = CONTENT_TOP + 80 + row * 360
            inside = max(abs(v) for v in vals) < 2
            color = graphics.PALETTE["accent"] if inside else (255, 107, 107)
            d.text((90, top), label, font=title_f, fill=color)
            d.text((90, top + 70), "stays small  →  inside" if inside else "runs away  →  outside",
                   font=lab_f, fill=graphics.PALETTE["text"])
            shown = 1 + int(_ease(t * 1.15) * (len(vals) - 1))
            base_y, bar_w, gap = top + 300, 110, 40
            for i, v in enumerate(vals[:shown]):
                h = min(150, abs(v) * 60 if inside else min(150, math.log2(1 + abs(v)) * 32))
                x = 90 + i * (bar_w + gap)
                d.rectangle((x, base_y - h, x + bar_w, base_y), fill=color if v >= 0 else (*color, 160))
                txt = f"{v:g}" if abs(v) < 1000 else f"{v:.2e}"
                d.text((x, base_y + 10), txt, font=val_f, fill=graphics.PALETTE["text"])
        fw.write(img)
    return fw.close()


def equation_card(out: Path, duration: float, **_) -> Path:
    parts = ["z", "  →  ", "z²", " + ", "c"]
    fw = FrameWriter(out)
    n = int(duration * FPS)
    big = graphics.font(150)
    small = graphics.font(46, bold=False)
    for k in range(n):
        t = k / max(1, n - 1)
        img = _bg()
        d = ImageDraw.Draw(img)
        shown = max(1, math.ceil(_ease(min(1.0, t * 1.6)) * len(parts)))
        text = "".join(parts[:shown])
        w = big.getlength("".join(parts))
        d.text(((W - w) / 2, 700), text, font=big, fill=graphics.PALETTE["text"])
        if t > 0.55:
            a = int(255 * _ease((t - 0.55) / 0.3))
            for i, line in enumerate(["start at z = 0", "repeat forever"]):
                lw = small.getlength(line)
                d.text(((W - lw) / 2, 930 + i * 70), line, font=small, fill=(*graphics.PALETTE["accent"], a))
        fw.write(img)
    return fw.close()


def _koch(points: list[tuple[float, float]], level: int) -> list[tuple[float, float]]:
    for _ in range(level):
        nxt = [points[0]]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            dx, dy = (x2 - x1) / 3, (y2 - y1) / 3
            a, b = (x1 + dx, y1 + dy), (x1 + 2 * dx, y1 + 2 * dy)
            px = a[0] + dx * 0.5 - dy * math.sqrt(3) / 2
            py = a[1] + dy * 0.5 + dx * math.sqrt(3) / 2
            nxt += [a, (px, py), b, (x2, y2)]
        points = nxt
    return points


def coastline(out: Path, duration: float, levels: list[int] | None = None, **_) -> Path:
    """A coastline-like curve (Koch curve) measured with shorter and shorter rulers: length × 4/3 each time."""
    levels = levels or [0, 1, 2, 3, 4]
    fw = FrameWriter(out)
    n = int(duration * FPS)
    f, sf = graphics.font(52), graphics.font(40, bold=False)
    base = [(110.0, 1280.0), (970.0, 1280.0)]
    for k in range(n):
        t = k / max(1, n - 1)
        lvl = levels[min(len(levels) - 1, int(t * len(levels)))]
        pts = _koch(base, lvl)
        img = _bg()
        d = ImageDraw.Draw(img)
        d.line([(x, 2000 - y) for x, y in pts], fill=graphics.PALETTE["accent"], width=6, joint="curve")
        d.text((90, CONTENT_TOP), "Measuring a coastline-like curve", font=f, fill=graphics.PALETTE["text"])
        ruler = "1" if lvl == 0 else f"1/{3 ** lvl}"
        length = (4 / 3) ** lvl
        d.text((90, 880), f"ruler: {ruler}", font=f, fill=graphics.PALETTE["muted"])
        d.text((90, 950), f"measured length: {length:.2f}", font=f, fill=graphics.PALETTE["highlight"])
        d.text((90, 1030), "shorter ruler → longer coast", font=sf, fill=graphics.PALETTE["muted"])
        fw.write(img)
    return fw.close()


def timeline(out: Path, duration: float, events: dict | None = None, active: str | None = None, **_) -> Path:
    events = events or {}
    years = sorted(events)
    fw = FrameWriter(out)
    n = int(duration * FPS)
    f, lf = graphics.font(52), graphics.font(38, bold=False)
    top, x0, x1 = 760, 140, 940
    for k in range(n):
        t = k / max(1, n - 1)
        img = _bg()
        d = ImageDraw.Draw(img)
        d.line((x0, top, x1, top), fill=graphics.PALETTE["muted"], width=6)
        for i, y in enumerate(years):
            x = x0 + (x1 - x0) * (i / (len(years) - 1) if len(years) > 1 else 0.5)
            on = y == active
            grow = _ease(min(1.0, t * 3)) if on else 1.0
            r = 14 + (14 * grow if on else 0)
            d.ellipse((x - r, top - r, x + r, top + r), fill=graphics.PALETTE["accent"] if on else graphics.PALETTE["muted"])
            w = f.getlength(y)
            yy = top + 40 if i % 2 == 0 else top - 110
            d.text((x - w / 2, yy), y, font=f, fill=graphics.PALETTE["text"] if on else graphics.PALETTE["muted"])
            if on and events.get(y):
                label = events[y]
                lw = lf.getlength(label)
                d.text((max(90, min(W - 90 - lw, x - lw / 2)), top + 200), label, font=lf, fill=graphics.PALETTE["highlight"])
        fw.write(img)
    return fw.close()


def kinetic_text(out: Path, duration: float, text: str = "", sub: str = "", **_) -> Path:
    fw = FrameWriter(out)
    n = int(duration * FPS)
    size = 160 if len(text) <= 9 else 110
    big, small = graphics.font(size), graphics.font(46, bold=False)
    lines = graphics.wrap(text, big, W - 180)
    for k in range(n):
        t = k / max(1, n - 1)
        img = _bg()
        d = ImageDraw.Draw(img)
        scale_in = _ease(min(1.0, t * 4))
        y = 760 - 40 * (1 - scale_in)
        for i, ln in enumerate(lines):
            w = big.getlength(ln)
            d.text(((W - w) / 2, y + i * (size + 20)), ln, font=big, fill=(*graphics.PALETTE["text"], int(255 * scale_in)))
        if sub:
            sw = small.getlength(sub)
            d.text(((W - sw) / 2, y + len(lines) * (size + 20) + 30), sub, font=small,
                   fill=(*graphics.PALETTE["accent"], int(255 * _ease(max(0.0, t * 3 - 0.6)))))
        fw.write(img)
    return fw.close()


def _hilbert(order: int) -> list[tuple[int, int]]:
    n = 2 ** order
    pts = []
    for i in range(n * n):
        x = y = 0
        t = i
        s = 1
        while s < n:
            rx = 1 & (t // 2)
            ry = 1 & (t ^ rx)
            if ry == 0:
                if rx == 1:
                    x, y = s - 1 - x, s - 1 - y
                x, y = y, x
            x += s * rx
            y += s * ry
            t //= 4
            s *= 2
        pts.append((x, y))
    return pts


def space_filling_curve(out: Path, duration: float, **_) -> Path:
    """Illustration: a single line (Hilbert curve) that comes closer and closer to filling a square."""
    fw = FrameWriter(out)
    n = int(duration * FPS)
    f, sf = graphics.font(56), graphics.font(40, bold=False)
    side, left, top = 600, 240, 440
    for k in range(n):
        t = k / max(1, n - 1)
        order = 3 + min(3, int(t * 4))
        pts = _hilbert(order)
        cell = side / (2 ** order)
        img = _bg()
        d = ImageDraw.Draw(img)
        d.line([(left + (x + 0.5) * cell, top + (y + 0.5) * cell) for x, y in pts],
               fill=graphics.PALETTE["accent"], width=max(2, int(cell * 0.2)))
        d.text((90, CONTENT_TOP), "A line that fills a surface", font=f, fill=graphics.PALETTE["text"])
        d.text((90, CONTENT_TOP + 70), "illustration of dimension 2", font=sf, fill=graphics.PALETTE["muted"])
        fw.write(img)
    return fw.close()


def life(out: Path, duration: float, pattern: str | None = None, **_) -> Path:
    from studio.sources.fixtures import GLIDER, GOSPER_GUN, make_life_clip
    pat = {"glider": GLIDER, "gosper_gun": GOSPER_GUN}.get(pattern or "")
    return make_life_clip(out, grid="72x128", rate=12, seconds=duration, pattern=pat, seed=5)


GENERATORS = {"mandelbrot_zoom": mandelbrot_zoom, "iteration_chart": iteration_chart, "equation_card": equation_card,
              "coastline": coastline, "timeline": timeline, "kinetic_text": kinetic_text,
              "space_filling_curve": space_filling_curve, "life": life}
DESCRIPTIONS = {
    "mandelbrot_zoom": "Procedural zoom into the Mandelbrot set rendered by FFmpeg's mandelbrot source",
    "iteration_chart": "Animated chart of z -> z^2 + c for c = -1 and c = 1",
    "equation_card": "Animated equation card z -> z^2 + c",
    "coastline": "Koch curve measured with shorter rulers (length grows by 4/3 per step)",
    "timeline": "Animated timeline of dated events",
    "kinetic_text": "Animated text card",
    "space_filling_curve": "Hilbert curve illustration of a line filling a square",
    "life": "Conway's Game of Life simulation rendered by FFmpeg",
}


def generate(ctx, generator: str, params: dict | None, duration: float, *, topic_id: str | None, tags: list[str]) -> dict:
    """Render (or reuse) a generated clip and register it as a rights-verified source."""
    if generator not in GENERATORS:
        raise ValidationError(f"Unknown visual generator {generator!r}; available: {sorted(GENERATORS)}")
    params = dict(params or {})
    duration = round(max(1.0, duration), 2)
    key = hashlib.sha1(json.dumps([generator, params, duration, GENERATOR_VERSION],
                                  sort_keys=True).encode()).hexdigest()[:12]
    out_dir = ctx.ws.home / "sources" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{generator}_{key}.mp4"
    if not out.exists():
        log.info("generating %s %s (%.1fs)", generator, params, duration)
        GENERATORS[generator](out, duration, **params)
    brand = ctx.brand.get("channel_name", "this channel")
    lic = LicenseInfo(
        license_type="CC0-1.0", license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        commercial_use_allowed=True, modification_allowed=True, attribution_required=False, audio_reuse_allowed=True,
        creator=f"{brand} (generated by ttengine.visuals)",
        permission_reference=f"self-generated: ttengine.visuals.{generator}",
        permission_date=today().isoformat(),
        permission_notes="Original procedural visual created by this project; no third-party material.",
        evidence_kind="manifest",
        evidence={"generator": generator, "params": params, "duration": duration, "description": DESCRIPTIONS[generator]},
    )
    cand = SourceCandidate(source_url=f"generated://{generator}/{key}", platform="generated",
                           title=f"{DESCRIPTIONS[generator]} ({key})", media_type="video", license=lic,
                           creator=lic.creator, description=DESCRIPTIONS[generator], tags=tags + [generator],
                           local_path=str(out), role="visual")
    sid, ok, reasons = discovery.record_candidate(ctx, cand, topic_id=topic_id)
    if not ok:
        raise RenderError(f"Generated visual failed the rights gate unexpectedly: {reasons}")
    src = ingest.ingest(ctx, sid)
    return {**src, "generator": generator, "params": params}
