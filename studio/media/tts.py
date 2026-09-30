"""Narration: TTS provider abstraction with word-level timestamps.

TTSProvider
├── EspeakNGProvider   local, offline. Word timings from libespeak-ng's synthesis
│                      callbacks (exact), or the CLI with proportional timing as a
│                      fallback. Voice quality is robotic: good for development
│                      and tests, not for publishing.
└── ElevenLabsProvider network (TTS_API_KEY). Uses the /with-timestamps endpoint
                       for character-level alignment. Implemented against the
                       documented API; not exercised live in this environment.

Narration is synthesised sentence by sentence so pauses are explicit and
controllable; a pronunciation lexicon changes only what is *spoken*, captions
keep the original spelling.
"""
from __future__ import annotations

import array
import base64
import ctypes
import ctypes.util
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from ..errors import ProviderError
from ..logging_setup import get_logger
from ..textutil import estimate_syllables, split_sentences

log = get_logger("media.tts")


@dataclass
class WordTiming:
    word: str          # as written (for captions)
    start: float
    end: float
    section: str = ""


@dataclass
class Segment:
    samples: np.ndarray          # int16 mono
    sample_rate: int
    events: list[tuple[int, float]]  # (0-based char offset in spoken text, seconds)


@dataclass
class TTSResult:
    audio_path: str
    duration: float
    sample_rate: int
    words: list[WordTiming]
    sections: list[dict] = field(default_factory=list)   # [{name, start, end}]
    sentences: list[dict] = field(default_factory=list)  # [{section, text, start, end}]
    provider: str = ""
    voice: str = ""
    chars: int = 0


class TTSProvider(ABC):
    name = "base"
    paid = False

    @abstractmethod
    def synthesize(self, text: str, *, wpm: int, pitch: int) -> Segment:
        ...


# ---------------------------------------------------------------------------
class _EspeakEvent(ctypes.Structure):
    class _Id(ctypes.Union):
        _fields_ = [("number", ctypes.c_int), ("name", ctypes.c_char_p), ("string", ctypes.c_char * 8)]
    _fields_ = [("type", ctypes.c_int), ("unique_identifier", ctypes.c_uint), ("text_position", ctypes.c_int),
                ("length", ctypes.c_int), ("audio_position", ctypes.c_int), ("sample", ctypes.c_int),
                ("user_data", ctypes.c_void_p), ("id", _Id)]


_SYNTH_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.POINTER(_EspeakEvent))
_ESPEAK_LOCK = threading.Lock()


class EspeakNGProvider(TTSProvider):
    name = "espeak"
    _lib = None
    _rate = None
    _buf: array.array | None = None
    _events: list | None = None
    _cb = None

    def __init__(self, voice: str = "en-us"):
        self.voice = voice
        self.mode = "library" if self._load() else ("cli" if shutil.which("espeak-ng") else None)
        if self.mode is None:
            raise ProviderError("espeak-ng is not installed", hint="apt-get install espeak-ng (or brew install espeak-ng)")

    @classmethod
    def _load(cls) -> bool:
        if cls._lib is not None:
            return True
        # Load the system library by absolute path. Other packages (e.g. kokoro-onnx's phonemizer)
        # may have loaded a bundled copy with the same soname; a bare-name load would return that
        # copy, which has its own data location and its own global state.
        candidates = [os.environ.get("STUDIO_ESPEAK_LIB"), "/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1",
                      "/usr/lib/aarch64-linux-gnu/libespeak-ng.so.1", "/usr/lib/libespeak-ng.so.1",
                      "/usr/local/lib/libespeak-ng.so.1", "/opt/homebrew/lib/libespeak-ng.dylib",
                      "/usr/local/lib/libespeak-ng.dylib"]
        path = next((c for c in candidates if c and os.path.exists(c)), None) \
            or ctypes.util.find_library("espeak-ng") or "libespeak-ng.so.1"
        try:
            lib = ctypes.CDLL(path)
        except OSError:
            return False
        data_parent = os.environ.get("STUDIO_ESPEAK_DATA_PARENT")
        if not data_parent and os.path.isabs(path) and os.path.isdir(os.path.join(os.path.dirname(path), "espeak-ng-data")):
            data_parent = os.path.dirname(path)
        rate = lib.espeak_Initialize(2, 0, data_parent.encode() if data_parent else None, 0)  # AUDIO_OUTPUT_SYNCHRONOUS
        if rate <= 0:
            return False

        def callback(wav, n, events):
            if wav and n > 0:
                cls._buf.extend(wav[:n])
            i = 0
            while events[i].type != 0:  # LIST_TERMINATED
                ev = events[i]
                if ev.type == 1:  # WORD
                    cls._events.append((ev.text_position - 1, ev.audio_position / 1000.0))
                i += 1
            return 0

        cls._cb = _SYNTH_CB(callback)
        lib.espeak_SetSynthCallback(cls._cb)
        cls._lib, cls._rate = lib, rate
        return True

    def synthesize(self, text: str, *, wpm: int, pitch: int) -> Segment:
        if self.mode == "library":
            return self._synth_lib(text, wpm, pitch)
        return self._synth_cli(text, wpm, pitch)

    def _synth_lib(self, text: str, wpm: int, pitch: int) -> Segment:
        cls = type(self)
        with _ESPEAK_LOCK:
            cls._buf, cls._events = array.array("h"), []
            lib = cls._lib
            if lib.espeak_SetVoiceByName(self.voice.encode()) != 0:
                raise ProviderError(f"espeak-ng voice {self.voice!r} not found", hint="see `espeak-ng --voices`")
            lib.espeak_SetParameter(1, int(wpm), 0)    # espeakRATE
            lib.espeak_SetParameter(3, int(pitch), 0)  # espeakPITCH
            data = text.encode("utf-8") + b"\0"
            err = lib.espeak_Synth(ctypes.c_char_p(data), len(data), 0, 1, 0, 1, None, None)  # POS_CHARACTER, CHARS_UTF8
            lib.espeak_Synchronize()
            if err != 0:
                raise ProviderError(f"espeak_Synth failed with code {err}")
            samples = np.frombuffer(cls._buf.tobytes(), dtype=np.int16).copy()
            return Segment(samples, cls._rate, list(cls._events))

    def _synth_cli(self, text: str, wpm: int, pitch: int) -> Segment:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.wav"
            subprocess.run(["espeak-ng", "-v", self.voice, "-s", str(wpm), "-p", str(pitch), "-w", str(out), text],
                           check=True, timeout=120, capture_output=True)
            with wave.open(str(out)) as w:
                rate = w.getframerate()
                samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).copy()
        return Segment(samples, rate, _proportional_events(text, len(samples) / rate))


def _proportional_events(text: str, duration: float) -> list[tuple[int, float]]:
    """Fallback timing: distribute time by estimated syllables."""
    spans = [(m.start(), m.group()) for m in re.finditer(r"\S+", text)]
    weights = [estimate_syllables(re.sub(r"[^\w]", "", w) or "a") + 0.3 for _, w in spans]
    total = sum(weights) or 1.0
    t, out = 0.0, []
    for (pos, _), wgt in zip(spans, weights):
        out.append((pos, t))
        t += duration * wgt / total
    return out


# ---------------------------------------------------------------------------
class ElevenLabsProvider(TTSProvider):
    name = "elevenlabs"
    paid = True
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"

    def __init__(self, http, *, api_key: str | None, voice_id: str | None, model_id: str = "eleven_multilingual_v2"):
        if not api_key or not voice_id:
            raise ProviderError("TTS_API_KEY and ELEVENLABS_VOICE_ID must be set for the ElevenLabs provider")
        self.http, self.api_key, self.voice_id, self.model_id = http, api_key, voice_id, model_id
        self.voice = voice_id

    def synthesize(self, text: str, *, wpm: int, pitch: int) -> Segment:
        resp = self.http.post_json(
            self.URL.format(voice_id=self.voice_id) + "?output_format=pcm_22050",
            json_body={"text": text, "model_id": self.model_id,
                       "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                                          "speed": max(0.7, min(1.2, wpm / 160))}},
            headers={"xi-api-key": self.api_key})
        data = resp.json()
        samples = np.frombuffer(base64.b64decode(data["audio_base64"]), dtype="<i2").copy()
        align = data.get("alignment") or {}
        starts = align.get("character_start_times_seconds") or []
        return Segment(samples, 22050, [(i, float(t)) for i, t in enumerate(starts)])


# ---------------------------------------------------------------------------
def load_lexicon(path: Path | None) -> dict[str, str]:
    if not path or not Path(path).is_file():
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k).lower(): str(v) for k, v in data.items()}


def _spoken(tokens: list[str], lexicon: dict[str, str]) -> tuple[str, list[tuple[int, int]]]:
    """Build the spoken string and each written token's (start, end) span inside it."""
    parts, spans, pos = [], [], 0
    for tok in tokens:
        core = re.sub(r"^\W+|\W+$", "", tok)
        key = core.lower().removesuffix("'s").removesuffix("’s")
        if key in lexicon:
            tok = tok.replace(core[: len(key)], lexicon[key], 1)
        spans.append((pos, pos + len(tok)))
        parts.append(tok)
        pos += len(tok) + 1
    return " ".join(parts), spans


def _trim(samples: np.ndarray, rate: int, threshold: int = 300, margin: float = 0.04) -> tuple[np.ndarray, float]:
    """Trim leading/trailing near-silence; returns (samples, seconds removed from the front)."""
    loud = np.nonzero(np.abs(samples.astype(np.int32)) > threshold)[0]
    if len(loud) == 0:
        return samples, 0.0
    m = int(margin * rate)
    a, b = max(0, loud[0] - m), min(len(samples), loud[-1] + m)
    return samples[a:b], a / rate


def narrate(provider: TTSProvider, sections: list[dict], *, out_wav: Path, wpm: int, pitch: int,
            sentence_pause: float, section_pause: float, hook_pitch_delta: int = 0, lexicon: dict | None = None,
            lead_in: float = 0.15, tail: float = 0.6) -> TTSResult:
    lexicon = lexicon or {}
    rate = None
    chunks: list[np.ndarray] = []
    words: list[WordTiming] = []
    sec_times, sent_times = [], []
    t = lead_in
    chars = 0
    for si, sec in enumerate(sections):
        if si > 0:
            t += section_pause - sentence_pause
        sec_start = t
        sentences = [s for item in sec["sentences"] for s in (split_sentences(item["text"]) or [item["text"]])]
        for sentence in sentences:
            tokens = sentence.split()
            spoken, spans = _spoken(tokens, lexicon)
            seg = provider.synthesize(spoken, wpm=wpm, pitch=pitch + (hook_pitch_delta if sec["name"] == "HOOK" else 0))
            chars += len(spoken)
            if rate is None:
                rate = seg.sample_rate
                chunks.append(np.zeros(int(lead_in * rate), dtype=np.int16))
            elif seg.sample_rate != rate:
                raise ProviderError("TTS provider changed sample rate between segments")
            samples, cut = _trim(seg.samples, rate)
            seg_dur = len(samples) / rate
            starts: list[float | None] = []
            for a, b in spans:
                ev = [tt for pos, tt in seg.events if a <= pos < b]
                starts.append(max(0.0, min(ev) - cut) if ev else None)
            # interpolate words that produced no event
            known = [(i, s) for i, s in enumerate(starts) if s is not None]
            for i, s in enumerate(starts):
                if s is None:
                    prev = max((k for k in known if k[0] < i), default=(-1, 0.0), key=lambda k: k[0])
                    nxt = min((k for k in known if k[0] > i), default=(len(starts), seg_dur), key=lambda k: k[0])
                    frac = (i - prev[0]) / (nxt[0] - prev[0])
                    starts[i] = prev[1] + frac * (nxt[1] - prev[1])
            for i, tok in enumerate(tokens):
                end = starts[i + 1] if i + 1 < len(tokens) else seg_dur
                words.append(WordTiming(tok, round(t + starts[i], 3), round(t + max(end, starts[i] + 0.05), 3), sec["name"]))
            chunks.append(samples)
            sent_times.append({"section": sec["name"], "text": sentence, "start": round(t, 3), "end": round(t + seg_dur, 3)})
            t += seg_dur
            chunks.append(np.zeros(int(sentence_pause * rate), dtype=np.int16))
            t += sentence_pause
        sec_times.append({"name": sec["name"], "start": round(sec_start, 3), "end": round(t - sentence_pause, 3)})
    if rate is None:
        raise ProviderError("Nothing to narrate")
    chunks.append(np.zeros(int(max(0.0, tail - sentence_pause) * rate), dtype=np.int16))
    audio = np.concatenate(chunks)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())
    return TTSResult(audio_path=str(out_wav), duration=round(len(audio) / rate, 3), sample_rate=rate, words=words,
                     sections=sec_times, sentences=sent_times, provider=provider.name,
                     voice=getattr(provider, "voice", ""), chars=chars)


def build_tts(ctx) -> TTSProvider:
    name = ctx.cfg.get("voice.provider")
    if name == "espeak":
        return EspeakNGProvider(ctx.cfg.get("voice.voice_name"))
    if name == "elevenlabs":
        return ElevenLabsProvider(ctx.http, api_key=ctx.cfg.secret("TTS_API_KEY"),
                                  voice_id=ctx.cfg.secret("ELEVENLABS_VOICE_ID") or ctx.cfg.get("voice.voice_name"))
    raise ProviderError(f"Unknown TTS provider {name!r}")
