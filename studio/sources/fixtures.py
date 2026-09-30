"""Self-generated, public-domain (CC0) test material.

The footage is synthesised by FFmpeg's `life` source (Conway's Game of Life),
so it is our own original work with no third-party rights, dedicated CC0.
The research notes are written in our own words and cite where each fact can
be checked. No copyrighted media is downloaded to build or test this project.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..media import ffmpeg
from ..textutil import today

GLIDER = [" O ", "  O", "OOO"]
GOSPER_GUN = [
    "                        O           ",
    "                      O O           ",
    "            OO      OO            OO",
    "           O   O    OO            OO",
    "OO        O     O   OO              ",
    "OO        O   O OO    O O           ",
    "          O     O       O           ",
    "           O   O                    ",
    "            OO                      ",
]

LIFE_COLORS = "life_color=#3CF08C:death_color=#0B1020:mold=12:mold_color=#1B3A5C"

CLIPS = [
    {"file": "life_random_soup.mp4", "grid": "90x160", "rate": 12, "seconds": 10, "pattern": None, "seed": 7,
     "title": "Random Game of Life soup settling into stable shapes",
     "tags": ["game of life", "cellular automaton", "random", "soup", "rules", "grid", "cells", "conway"],
     "description": "A random starting grid evolving under Conway's rules (B3/S23), rendered by FFmpeg."},
    {"file": "life_glider.mp4", "grid": "45x80", "rate": 8, "seconds": 10, "pattern": GLIDER,
     "title": "A single glider travelling diagonally",
     "tags": ["glider", "game of life", "pattern", "moves", "diagonal", "richard guy", "spaceship"],
     "description": "A five-cell glider moving one cell diagonally every four generations."},
    {"file": "life_gosper_gun.mp4", "grid": "72x128", "rate": 15, "seconds": 12, "pattern": GOSPER_GUN,
     "title": "Gosper glider gun emitting a stream of gliders",
     "tags": ["gosper", "glider gun", "gun", "infinite growth", "prize", "mit", "game of life", "computation"],
     "description": "The Gosper glider gun, which emits a new glider every 30 generations."},
    {"file": "life_landscape_soup.mp4", "grid": "160x90", "rate": 12, "seconds": 8, "pattern": None, "seed": 11,
     "title": "Wide-format Game of Life soup",
     "tags": ["game of life", "wide", "soup", "grid", "cells", "turing", "computer"],
     "description": "Landscape-format random soup used to exercise 16:9 to 9:16 reframing."},
]

NOTES = {
    "topic": "Conway's Game of Life",
    "category": "science",
    "notes_author": "project fixtures (written in our own words)",
    "verification_note": ("URLs below were written from the fixture author's knowledge and were not fetched in the "
                          "build environment (network access to them was blocked). Open each link before publishing."),
    "sources": [
        {"id": "s1", "title": "Conway's Game of Life (Wikipedia)",
         "url": "https://en.wikipedia.org/wiki/Conway%27s_Game_of_Life", "reliability": "tertiary"},
        {"id": "s2", "title": "Glider (LifeWiki)", "url": "https://conwaylife.com/wiki/Glider", "reliability": "secondary"},
        {"id": "s3", "title": "Gosper glider gun (LifeWiki)", "url": "https://conwaylife.com/wiki/Gosper_glider_gun",
         "reliability": "secondary"},
        {"id": "s4", "title": "Gardner, M. (October 1970). Mathematical Games. Scientific American, 223(4), 120-123.",
         "url": None, "reliability": "primary"},
    ],
    "facts": [
        {"id": "f1", "text": "The British mathematician John Conway invented the Game of Life in 1970.",
         "sources": ["s1"], "tags": ["origin", "person", "setup"], "date": "1970"},
        {"id": "f2", "text": "It reached the public through Martin Gardner's Mathematical Games column in Scientific American in October 1970.",
         "sources": ["s1", "s4"], "tags": ["origin", "history", "setup"], "date": "1970-10"},
        {"id": "f3", "text": "Nobody actually plays it. Once the first pattern is placed, the game runs entirely on its own.",
         "sources": ["s1"], "tags": ["definition", "hook", "setup"],
         "question": "What kind of game runs without a single player?"},
        {"id": "f4", "text": "The board is a grid of square cells, and every cell is either alive or dead.",
         "sources": ["s1"], "tags": ["mechanism", "development"]},
        {"id": "f5", "text": "A living cell stays alive only if it has two or three living neighbours.",
         "sources": ["s1"], "tags": ["mechanism", "rule", "development"]},
        {"id": "f6", "text": "An empty cell comes to life when exactly three of its neighbours are alive.",
         "sources": ["s1"], "tags": ["mechanism", "rule", "development"]},
        {"id": "f7", "text": "Richard Guy spotted the glider in 1970: five cells that crawl diagonally across the grid, rebuilding their shape every four generations.",
         "sources": ["s2"], "tags": ["glider", "pattern", "development", "visual"], "date": "1970"},
        {"id": "f8", "text": "Conway suspected no pattern could grow forever, and he offered fifty dollars to anyone who could prove him wrong.",
         "sources": ["s1"], "tags": ["stakes", "hook", "contrast", "development"]},
        {"id": "f9", "text": "In November 1970 a team at MIT led by Bill Gosper won the money with the glider gun, which fires a fresh glider every thirty generations.",
         "sources": ["s1", "s3"], "tags": ["gosper", "payoff", "glider gun"], "date": "1970-11"},
        {"id": "f10", "text": "Streams of gliders can carry signals, and with them Life can be wired into a working computer. It is Turing complete.",
         "sources": ["s1"], "tags": ["payoff", "significance", "computation"]},
    ],
    "hook_ideas": [
        "This game has rules, a board, and zero players.",
        "In 1970, Conway bet fifty dollars that this could not happen.",
    ],
}


def write_pattern(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def make_life_clip(out: Path, *, grid: str, rate: int, seconds: float, pattern: list[str] | None = None,
                   seed: int = 1, width: int | None = None, height: int | None = None, fps: int = 30) -> Path:
    gw, gh = (int(x) for x in grid.split("x"))
    width = width or (1080 if gw < gh else 1920)
    height = height or (1920 if gw < gh else 1080)
    if pattern:
        pfile = write_pattern(out.with_suffix(".pattern.txt"), pattern)
        src = f"life=f={pfile}:s={grid}:r={rate}:{LIFE_COLORS}"
    else:
        src = f"life=s={grid}:r={rate}:ratio=0.33:random_seed={seed}:{LIFE_COLORS}"
    ffmpeg.ffmpeg(["-f", "lavfi", "-i", src, "-t", str(seconds),
                   "-vf", f"scale={width}:{height}:flags=neighbor,fps={fps},format=yuv420p",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-an", str(out)], what="fixture-clip")
    pat = out.with_suffix(".pattern.txt")
    if pat.exists():
        pat.unlink()
    return out


def sidecar(clip: dict) -> dict:
    return {
        "title": clip["title"], "creator": "Shorts Studio fixture generator",
        "license_type": "CC0-1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "commercial_use_allowed": True, "modification_allowed": True, "attribution_required": False,
        "audio_reuse_allowed": True,
        "permission_reference": "self-generated: ffmpeg lavfi 'life' source (no third-party material)",
        "permission_date": today().isoformat(),
        "permission_notes": "Original synthetic footage produced by this project and dedicated to the public domain.",
        "tags": clip["tags"], "description": clip["description"], "role": "visual",
    }


def build_fixture_library(library_dir: Path, notes_dir: Path, *, only: list[str] | None = None) -> list[Path]:
    library_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for clip in CLIPS:
        if only and clip["file"] not in only:
            continue
        out = library_dir / clip["file"]
        if not out.exists():
            make_life_clip(out, grid=clip["grid"], rate=clip["rate"], seconds=clip["seconds"],
                           pattern=clip["pattern"], seed=clip.get("seed", 1))
        side = out.with_name(out.name + ".rights.yaml")
        side.write_text(yaml.safe_dump(sidecar(clip), sort_keys=False), encoding="utf-8")
        made.append(out)
    notes_path = notes_dir / "conways-game-of-life.yaml"
    notes_path.write_text(yaml.safe_dump(NOTES, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return made


def make_watermarked_clip(out: Path, seconds: float = 6) -> Path:
    """Test-only: moving footage with a static corner logo, to exercise the watermark heuristic."""
    src = f"life=s=90x160:r=12:ratio=0.35:random_seed=3:{LIFE_COLORS}"
    ffmpeg.ffmpeg(["-f", "lavfi", "-i", src, "-t", str(seconds), "-vf",
                   "scale=540:960:flags=neighbor,drawbox=x=380:y=20:w=140:h=60:color=white@1:t=fill,"
                   "drawbox=x=395:y=35:w=110:h=30:color=black@1:t=fill,fps=30,format=yuv420p",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-an", str(out)], what="fixture-watermark")
    return out
