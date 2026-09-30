"""Thin, logged, time-limited wrappers around ffmpeg/ffprobe."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import RenderError
from ..logging_setup import get_logger

log = get_logger("studio.render")


def require_binaries() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise RenderError(f"Missing required binaries: {', '.join(missing)}",
                          hint="install ffmpeg (e.g. `apt-get install ffmpeg` or `brew install ffmpeg`)")


def run(args: list[str], *, timeout: float = 900, what: str = "ffmpeg", capture_stdout: bool = False,
        check: bool = True) -> subprocess.CompletedProcess:
    cmd = [str(a) for a in args]
    log.debug("%s: %s", what, " ".join(cmd))
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        log.error("%s timed out after %ss", what, timeout)
        raise RenderError(f"{what} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise RenderError(f"{cmd[0]} not found", hint="install ffmpeg") from exc
    stderr = proc.stderr.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-15:])
        log.error("%s failed (exit %s):\n%s", what, proc.returncode, tail)
        raise RenderError(f"{what} failed (exit {proc.returncode}): {tail.splitlines()[-1] if tail else ''}")
    proc.stderr_text = stderr  # type: ignore[attr-defined]
    return proc


def ffmpeg(args: list[str], **kw) -> subprocess.CompletedProcess:
    return run(["ffmpeg", "-hide_banner", "-nostdin", "-y", *args], **kw)


@dataclass
class MediaInfo:
    path: str
    duration: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    pix_fmt: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    nb_frames: int | None = None
    bit_rate: int | None = None


def _rate(text: str | None) -> float | None:
    if not text or text in ("0/0", "0"):
        return None
    if "/" in text:
        n, d = text.split("/")
        return float(n) / float(d) if float(d) else None
    return float(text)


def probe(path: str | Path) -> MediaInfo:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
               capture_stdout=True, what="ffprobe", timeout=60)
    data = json.loads(proc.stdout.decode("utf-8") or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or (v or a or {}).get("duration") or 0.0)
    return MediaInfo(
        path=str(path), duration=duration, has_video=v is not None, has_audio=a is not None,
        width=int(v["width"]) if v else None, height=int(v["height"]) if v else None,
        fps=_rate(v.get("avg_frame_rate") or v.get("r_frame_rate")) if v else None,
        video_codec=v.get("codec_name") if v else None, audio_codec=a.get("codec_name") if a else None,
        pix_fmt=v.get("pix_fmt") if v else None,
        sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        channels=int(a["channels"]) if a and a.get("channels") else None,
        nb_frames=int(v["nb_frames"]) if v and str(v.get("nb_frames", "")).isdigit() else None,
        bit_rate=int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
    )


_BLACK_RE = re.compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)")
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*([\d.]+)")


def detect_black(path: str | Path, *, min_duration: float = 0.1, pix_th: float = 0.10) -> list[tuple[float, float]]:
    proc = ffmpeg(["-i", str(path), "-vf", f"blackdetect=d={min_duration}:pix_th={pix_th}", "-an", "-f", "null", "-"],
                  what="blackdetect")
    return [(float(a), float(b)) for a, b in _BLACK_RE.findall(proc.stderr_text)]


def detect_silence(path: str | Path, *, noise_db: float = -45.0, min_duration: float = 0.5) -> list[tuple[float, float]]:
    proc = ffmpeg(["-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}", "-vn", "-f", "null", "-"],
                  what="silencedetect")
    starts = [max(0.0, float(x)) for x in _SIL_START.findall(proc.stderr_text)]
    ends = [float(x) for x in _SIL_END.findall(proc.stderr_text)]
    if len(ends) < len(starts):  # silence runs to the end of the file
        ends.append(probe(path).duration)
    return list(zip(starts, ends))


def loudness(path: str | Path) -> dict:
    """Integrated loudness (LUFS), true peak (dBTP) and LRA via loudnorm's analysis pass."""
    proc = ffmpeg(["-i", str(path), "-af", "loudnorm=print_format=json", "-vn", "-f", "null", "-"], what="loudness")
    text = proc.stderr_text
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise RenderError("could not parse loudnorm output")
    data = json.loads(text[start:end + 1])
    def f(key):
        try:
            return float(data[key])
        except (KeyError, ValueError):
            return float("-inf")
    return {"integrated_lufs": f("input_i"), "true_peak_db": f("input_tp"), "lra": f("input_lra")}


def decode_errors(path: str | Path) -> list[str]:
    proc = ffmpeg(["-v", "error", "-i", str(path), "-f", "null", "-"], what="decode-check", check=False)
    lines = [ln for ln in proc.stderr_text.splitlines() if ln.strip()]
    if proc.returncode != 0 and not lines:
        lines = [f"decoder exited with {proc.returncode}"]
    return lines


def gray_frames(path: str | Path, *, fps: float = 2.0, width: int = 96, max_seconds: float | None = None) -> tuple[np.ndarray, list[float]]:
    """Decode frames as small grayscale arrays (N, H, W) for analysis, with their timestamps."""
    info = probe(path)
    if not info.has_video or not info.width:
        return np.zeros((0, 1, 1), dtype=np.uint8), []
    height = max(2, int(round(info.height * width / info.width / 2)) * 2)
    args = ["-v", "error", "-i", str(path)]
    if max_seconds:
        args += ["-t", str(max_seconds)]
    args += ["-vf", f"fps={fps},scale={width}:{height},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = ffmpeg(args, capture_stdout=True, what="frame-extract", timeout=600)
    raw = np.frombuffer(proc.stdout, dtype=np.uint8)
    frame_size = width * height
    n = len(raw) // frame_size
    frames = raw[: n * frame_size].reshape(n, height, width)
    return frames, [i / fps for i in range(n)]


def extract_frame(path: str | Path, t: float, out: Path, *, width: int | None = None) -> Path:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1", *vf, str(out)], what="extract-frame")
    return out
