"""Voice engine: TTS providers that plug into the studio narration pipeline.

TTSProvider (studio.media.tts)
├── KokoroProvider      local neural voice (Kokoro-82M, Apache-2.0), word timings via forced alignment
├── EspeakNGProvider    local, robotic; exact word timings (development / alignment reference)
└── ElevenLabsProvider  cloud (TTS_API_KEY), character timings from the API

Voice, speed, pitch (espeak), pauses (sentence/section) and pronunciation are
configurable; "emotion" is not exposed by these providers, so it is not faked.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from studio.errors import ProviderError
from studio.media.tts import ElevenLabsProvider, EspeakNGProvider, Segment, TTSProvider, load_lexicon
from . import align

MODEL_FILES = {"model": "kokoro-v1.0.int8.onnx", "voices": "voices-v1.0.bin"}
MODEL_LICENSE = "Kokoro-82M weights: Apache-2.0 (hexgrad/Kokoro-82M); kokoro-onnx: MIT"


class KokoroProvider(TTSProvider):
    name = "kokoro"
    paid = False
    _engine = None
    _lock = threading.Lock()

    def __init__(self, models_dir: Path, voice: str = "am_michael", speed: float = 1.0, lang: str = "en-us"):
        models_dir = Path(models_dir)
        model, voices = models_dir / MODEL_FILES["model"], models_dir / MODEL_FILES["voices"]
        if not model.is_file() or not voices.is_file():
            raise ProviderError(f"Kokoro model files not found in {models_dir}",
                                hint="run `python main.py voice --download` or set voice.provider: espeak")
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise ProviderError("kokoro-onnx is not installed", hint="pip install kokoro-onnx") from exc
        with KokoroProvider._lock:
            if KokoroProvider._engine is None:
                KokoroProvider._engine = Kokoro(str(model), str(voices))
        if voice not in KokoroProvider._engine.get_voices():
            raise ProviderError(f"Unknown Kokoro voice {voice!r}", hint="see `python main.py voice --list`")
        self.voice, self.speed, self.lang = voice, speed, lang
        self.reference = EspeakNGProvider("en-us")

    @classmethod
    def voices(cls) -> list[str]:
        return cls._engine.get_voices() if cls._engine else []

    def synthesize(self, text: str, *, wpm: int, pitch: int) -> Segment:
        with KokoroProvider._lock:
            audio, sr = KokoroProvider._engine.create(text, voice=self.voice, speed=self.speed, lang=self.lang)
        samples = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        ref = self.reference.synthesize(text, wpm=170, pitch=50)
        times = align.align(ref.samples, ref.sample_rate, [t for _, t in ref.events], samples, sr)
        return Segment(samples, sr, [(pos, t) for (pos, _), t in zip(ref.events, times)])


def build(ctx, voice_name: str | None = None) -> tuple[TTSProvider, dict]:
    """Returns (provider, lexicon). Respellings are tuned for espeak, so Kokoro uses its own lexicon if any."""
    cfg = ctx.cfg
    name = cfg.get("voice.provider")
    voice = voice_name or cfg.get("voice.voice_name")
    lex_file = cfg.config_file(cfg.get("voice.pronunciation_file"))
    if name == "kokoro":
        provider = KokoroProvider(cfg.path(cfg.get("voice.models_dir")), voice=voice,
                                  speed=float(cfg.get("voice.speed", 1.0)))
        kokoro_lex = cfg.get("voice.kokoro_pronunciation_file", None)
        return provider, load_lexicon(cfg.config_file(kokoro_lex)) if kokoro_lex else {}
    if name == "espeak":
        return EspeakNGProvider(voice if voice.startswith("en") else "en-us"), load_lexicon(lex_file)
    if name == "elevenlabs":
        return ElevenLabsProvider(ctx.http, api_key=cfg.secret("TTS_API_KEY"),
                                  voice_id=cfg.secret("ELEVENLABS_VOICE_ID") or voice), load_lexicon(lex_file)
    raise ProviderError(f"Unknown voice provider {name!r}")


def download_models(models_dir: Path, http=None) -> list[Path]:
    """Fetch the Kokoro model files from the kokoro-onnx GitHub release (Apache-2.0 weights)."""
    from studio.http import HttpClient
    http = http or HttpClient(timeout=600, min_interval=0)
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
    out = []
    for fname in MODEL_FILES.values():
        dest = Path(models_dir) / fname
        if not dest.exists():
            http.download(base + fname, dest, max_bytes=400_000_000)
        out.append(dest)
    return out


CALIBRATION_SENTENCES = [
    "Mathematicians study shapes that repeat at every scale.",
    "Measure a coastline with a shorter ruler, and you trace more bays and bends, so the total keeps growing.",
    "The same idea explains mountains, clouds, and the branching of rivers.",
]


def calibrate(provider: TTSProvider) -> float:
    """Measured words per minute for this voice, synthesising sentence by sentence like the narrator does."""
    from studio.media.tts import _trim
    words, seconds = 0, 0.0
    for sentence in CALIBRATION_SENTENCES:
        seg = provider.synthesize(sentence, wpm=160, pitch=50)
        samples, _ = _trim(seg.samples, seg.sample_rate)
        seconds += len(samples) / seg.sample_rate
        words += len(sentence.split())
    return round(words / seconds * 60, 1)


def effective_wpm(ctx, voice_name: str | None = None) -> float:
    """The speaking rate scripts should budget for: measured once per voice setting, then cached."""
    cfg = ctx.cfg
    name = cfg.get("voice.provider")
    if name == "espeak":
        return float(cfg.get("voice.words_per_minute"))
    voice = voice_name or cfg.get("voice.voice_name")
    key = f"calibration_{name}_{voice}_{cfg.get('voice.speed', 1.0)}"
    row = ctx.db.get("voices", key)
    if row and (row.get("settings_json") or {}).get("calibrated_wpm"):
        return float(row["settings_json"]["calibrated_wpm"])
    provider, _ = build(ctx, voice)
    wpm = calibrate(provider)
    from studio.textutil import now_iso
    ctx.db.insert("voices", {"voice_id": key, "provider": name, "voice_name": voice,
                             "settings_json": {"calibrated_wpm": wpm, "speed": cfg.get("voice.speed", 1.0)},
                             "created_at": now_iso()}, or_replace=True)
    return wpm
