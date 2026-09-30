"""Audio engine: VOICE / MUSIC / SFX / AMBIENCE tracks -> a clean, loudness-consistent mix.

* voice: high-pass, two-pass EBU R128 normalisation, limiter
* music/ambience: only licensed tracks (approved rights records); ducked under
  the voice with a sidechain compressor
* sfx: only licensed files, placed at given times
* master: limiter at the configured true peak, final loudness check
Every track is written separately so it can be inspected or remixed.
"""
from __future__ import annotations

from pathlib import Path

from ..errors import RenderError
from . import ffmpeg

SR = 48000


def silent_track(out: Path, duration: float) -> Path:
    ffmpeg.ffmpeg(["-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{duration:.3f}",
                   "-c:a", "pcm_s16le", str(out)], what="silent-track")
    return out


def master_voice(src: Path, out: Path, *, target_lufs: float, true_peak: float) -> dict:
    """Two-pass loudnorm so narration lands on target without pumping."""
    pre = out.with_name(out.stem + "_pre.wav")
    ffmpeg.ffmpeg(["-i", str(src), "-af", "highpass=f=70,aresample=48000", "-ac", "1", "-c:a", "pcm_s16le", str(pre)],
                  what="voice-prep")
    m = ffmpeg.loudness(pre)
    if m["integrated_lufs"] == float("-inf"):
        raise RenderError("Narration is silent — TTS produced no audible speech")
    af = (f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:measured_I={m['integrated_lufs']}:"
          f"measured_TP={m['true_peak_db']}:measured_LRA={m['lra']}:measured_thresh={m['threshold']}:linear=true,"
          f"aresample={SR},alimiter=limit={10 ** (true_peak / 20):.4f}:level=disabled")
    ffmpeg.ffmpeg(["-i", str(pre), "-af", af, "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(out)],
                  what="voice-master")
    pre.unlink(missing_ok=True)
    return m


def music_bed(src: Path, out: Path, duration: float, *, gain_db: float = -18.0) -> Path:
    fade_out = max(0.0, duration - 1.5)
    ffmpeg.ffmpeg(["-stream_loop", "-1", "-i", str(src), "-t", f"{duration:.3f}",
                   "-af", f"volume={gain_db}dB,afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.5,aresample={SR}",
                   "-ac", "2", "-c:a", "pcm_s16le", str(out)], what="music-bed")
    return out


def sfx_track(events: list[tuple[float, Path]], out: Path, duration: float, *, gain_db: float = -10.0) -> Path:
    if not events:
        return silent_track(out, duration)
    args, labels = [], []
    for i, (t, path) in enumerate(events):
        args += ["-i", str(path)]
        ms = int(t * 1000)
        labels.append(f"[{i}:a]volume={gain_db}dB,adelay={ms}|{ms},aresample={SR}[s{i}]")
    mix = "".join(f"[s{i}]" for i in range(len(events)))
    fc = ";".join(labels) + f";{mix}amix=inputs={len(events)}:normalize=0,apad,atrim=0:{duration:.3f}[out]"
    ffmpeg.ffmpeg([*args, "-filter_complex", fc, "-map", "[out]", "-ac", "2", "-c:a", "pcm_s16le", str(out)],
                  what="sfx-track")
    return out


def mix(voice: Path, music: Path, sfx: Path, ambience: Path, out: Path, *, duration: float, duck_db: float,
        target_lufs: float, true_peak: float) -> Path:
    """Duck music+ambience under the voice, sum all four tracks, limit, and normalise the master."""
    ratio = max(2.0, min(20.0, duck_db / 1.5))
    fc = (f"[0:a]asplit=2[v][key];"
          f"[1:a][3:a]amix=inputs=2:normalize=0[bed];"
          f"[bed][key]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:attack=15:release=350[ducked];"
          f"[v][ducked][2:a]amix=inputs=3:normalize=0,atrim=0:{duration:.3f},"
          f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11,aresample={SR},"
          f"alimiter=limit={10 ** (true_peak / 20):.4f}:level=disabled[out]")
    ffmpeg.ffmpeg(["-i", str(voice), "-i", str(music), "-i", str(sfx), "-i", str(ambience),
                   "-filter_complex", fc, "-map", "[out]", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(out)],
                  what="audio-mix")
    return out


def build_tracks(ctx, *, voice_raw: Path, out_dir: Path, duration: float, music_file: Path | None = None,
                 sfx_events: list[tuple[float, Path]] | None = None, ambience_file: Path | None = None) -> dict:
    cfg = ctx.cfg
    out_dir.mkdir(parents=True, exist_ok=True)
    target, tp = float(cfg.get("audio.target_lufs")), float(cfg.get("audio.true_peak_db"))
    voice = out_dir / "voice.wav"
    measured = master_voice(voice_raw, voice, target_lufs=target, true_peak=tp)
    music = out_dir / "music.wav"
    if music_file:
        music_bed(music_file, music, duration)
    else:
        silent_track(music, duration)
    sfx = sfx_track(sfx_events or [], out_dir / "sfx.wav", duration)
    amb = out_dir / "ambience.wav"
    if ambience_file:
        music_bed(ambience_file, amb, duration, gain_db=-24.0)
    else:
        silent_track(amb, duration)
    mixed = mix(voice, music, sfx, amb, out_dir / "mix.wav", duration=duration,
                duck_db=float(cfg.get("music.duck_db")), target_lufs=target, true_peak=tp)
    return {"voice": voice, "music": music, "sfx": sfx, "ambience": amb, "mix": mixed,
            "voice_measurement": measured, "mix_loudness": ffmpeg.loudness(mixed)}
