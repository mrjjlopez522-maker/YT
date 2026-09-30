"""Video assembly with FFmpeg.

Per scene: frame-exact clip (framing -> motion effect -> timed overlays), then
concat, then a final pass that burns captions and the progress bar, muxes the
mixed audio and encodes a YouTube-friendly 1080x1920 H.264/AAC MP4.
Source audio is never used here: the soundtrack is our own mix.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..errors import RenderError
from ..logging_setup import get_logger
from . import ffmpeg, graphics

log = get_logger("studio.render")


def _frames(t: float, fps: int) -> int:
    return int(round(t * fps))


def _effect(effect: str, n: int, w: int, h: int, fps: int) -> str:
    n = max(1, n)
    punch = max(1, int(0.35 * fps))
    z = {
        "punch_in": f"if(lt(on,{punch}),1+0.12*on/{punch},1.12)",
        "slow_zoom_in": f"1+0.08*on/{n}",
        "slow_zoom_out": f"1.08-0.08*on/{n}",
        "pan": "1.12",
    }.get(effect, "1")
    x = f"(iw-iw/zoom)*on/{n}" if effect == "pan" else "iw/2-(iw/zoom/2)"
    return f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps}"


def _framing(framing: str, w: int, h: int) -> str:
    if framing == "blur_fill":
        return (f"split=2[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"gblur=sigma=40,eq=brightness=-0.10[bg];[b]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def overlay_images(scene: dict, work: Path, size: tuple[int, int]) -> list[tuple[Path, float, float | None]]:
    """Render the scene's graphics to PNGs. Returns (path, start, end) relative to the scene."""
    out = []
    for k, g in enumerate(scene.get("graphics") or []):
        kind = g["type"]
        if kind == "background_card":
            continue
        if kind == "title_card":
            img = graphics.title_card(g["text"], size)
        elif kind == "timeline":
            img = graphics.timeline(g["years"], g["active"], size, label=g.get("label"))
        elif kind == "highlight_box":
            img = graphics.highlight_box(tuple(g["box"]), size, label=g.get("label"))
        elif kind == "fact_card":
            img = graphics.fact_card(g.get("heading", ""), g.get("lines", []), size)
        elif kind == "attribution":
            img = graphics.attribution(g["text"], size)
        elif kind == "arrow":
            img = graphics.arrow(tuple(g["start_xy"]), tuple(g["end_xy"]), size)
        elif kind == "image":  # a pre-rendered full-frame RGBA overlay (e.g. brand cards)
            from PIL import Image
            img = Image.open(g["path"]).convert("RGBA").resize(size)
        else:
            raise RenderError(f"Unknown graphic type {kind!r}")
        path = graphics.save(img, work / f"scene{scene['idx']:02d}_g{k}_{kind}.png")
        out.append((path, float(g.get("start", 0.0)), g.get("end")))
    return out


def render_scene(scene: dict, src_path: str | None, src_duration: float | None, work: Path, *,
                 size: tuple[int, int], fps: int, frames: int) -> Path:
    w, h = size
    dur = frames / fps
    out = work / f"scene{scene['idx']:02d}.mp4"
    args: list[str] = []
    if scene["visual_type"] == "graphic":
        card = next((g for g in scene.get("graphics") or [] if g["type"] == "background_card"), None)
        bg = graphics.save(graphics.graphic_background(card["heading"] if card else "", card["lines"] if card else [],
                                                       size), work / f"scene{scene['idx']:02d}_bg.png")
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur + 0.5:.3f}", "-i", str(bg)]
        base = f"[0:v]fps={fps},{_effect(scene.get('effect') or 'slow_zoom_in', frames, w, h, fps)},setsar=1[base]"
    elif scene["visual_type"] == "still":
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur + 0.5:.3f}", "-i", str(src_path)]
        base = (f"[0:v]{_framing(scene.get('framing', 'crop'), w, h)},fps={fps},"
                f"{_effect(scene.get('effect') or 'slow_zoom_in', frames, w, h, fps)},setsar=1[base]")
    else:
        s_in = float(scene.get("source_in") or 0.0)
        need_loop = src_duration is not None and s_in + dur > src_duration - 0.05
        if need_loop:
            args += ["-stream_loop", "-1"]
        args += ["-ss", f"{s_in:.3f}", "-t", f"{dur + 0.5:.3f}", "-i", str(src_path)]
        base = (f"[0:v]fps={fps},{_framing(scene.get('framing', 'crop'), w, h)},"
                f"{_effect(scene.get('effect') or 'slow_zoom_in', frames, w, h, fps)},setsar=1[base]")

    chain = [base]
    last = "base"
    for i, (png, start, end) in enumerate(overlay_images(scene, work, size), start=1):
        end = min(float(end), dur) if end is not None else dur
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur + 0.5:.3f}", "-i", str(png)]
        fade_out = max(start, end - 0.25)
        chain.append(f"[{i}:v]format=rgba,fade=in:st={start:.3f}:d=0.25:alpha=1,"
                     f"fade=out:st={fade_out:.3f}:d=0.25:alpha=1[o{i}]")
        chain.append(f"[{last}][o{i}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{i}]")
        last = f"v{i}"
    chain.append(f"[{last}]format=yuv420p[out]")
    ffmpeg.ffmpeg([*args, "-filter_complex", ";".join(chain), "-map", "[out]", "-frames:v", str(frames),
                   "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-an", str(out)],
                  what=f"render-scene-{scene['idx']}", timeout=900)
    return out


def _escape_filter_path(name: str) -> str:
    return name.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def render_video(*, scenes: list[dict], sources_by_id: dict, audio_mix: Path, ass_path: Path, duration: float,
                 out_path: Path, work: Path, cfg) -> ffmpeg.MediaInfo:
    ffmpeg.require_binaries()
    size = cfg.resolution
    fps = int(cfg.get("production.fps"))
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    total_frames = _frames(duration, fps)
    for i, sc in enumerate(scenes):
        f0 = _frames(sc["start_time"], fps)
        f1 = total_frames if i == len(scenes) - 1 else _frames(scenes[i + 1]["start_time"], fps)
        if f1 <= f0:
            raise RenderError(f"Scene {sc['idx']} has no frames ({sc['start_time']}-{sc['end_time']})")
        src = sources_by_id.get(sc.get("visual_source")) if sc.get("visual_source") else None
        clips.append(render_scene(sc, src.get("local_path") if src else None, src.get("duration") if src else None,
                                  work, size=size, fps=fps, frames=f1 - f0))
    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    joined = work / "video_only.mp4"
    ffmpeg.ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_list.name, "-c", "copy", joined.name],
                  what="concat", cwd=work)

    bar = graphics.save(graphics.progress_bar(size[0], 10), work / "progress.png")
    local_ass = work / "captions.ass"
    if Path(ass_path).resolve() != local_ass.resolve():
        shutil.copy2(ass_path, local_ass)
    fc = (f"[2:v]format=rgba[pb];[0:v][pb]overlay=x='-w+w*t/{duration:.3f}':y=0:shortest=1[pv];"
          f"[pv]ass={_escape_filter_path(local_ass.name)},format=yuv420p[vout]")
    maxrate = str(cfg.get("production.video_maxrate"))
    bufsize = f"{int(maxrate.rstrip('Mk')) * 2}{maxrate[-1]}" if maxrate[-1] in "Mk" else maxrate
    tmp_out = work / "final.mp4"
    ffmpeg.ffmpeg([
        "-i", joined.name, "-i", str(Path(audio_mix).resolve()), "-loop", "1", "-framerate", str(fps), "-i", bar.name,
        "-filter_complex", fc, "-map", "[vout]", "-map", "1:a",
        "-c:v", "libx264", "-preset", str(cfg.get("production.x264_preset")), "-crf", str(cfg.get("production.x264_crf")),
        "-maxrate", maxrate, "-bufsize", bufsize, "-profile:v", "high", "-level:v", "4.2", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-g", str(fps * 2),
        "-c:a", "aac", "-b:a", str(cfg.get("production.audio_bitrate")), "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", tmp_out.name,
    ], what="final-encode", cwd=work, timeout=1800)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_out), str(out_path))
    info = ffmpeg.probe(out_path)
    log.info("rendered %s: %sx%s %.2fs %sfps", out_path.name, info.width, info.height, info.duration, info.fps)
    return info
