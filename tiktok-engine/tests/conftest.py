import shutil
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
import ttengine  # noqa: E402,F401  (puts the core `studio` library on sys.path)
from ttengine.context import TikTokContext  # noqa: E402

FIXTURE_NOTES = ENGINE / "fixtures" / "notes"
# Tests use the local espeak voice (no model download) and offline providers only.
FAST = {"voice": {"provider": "espeak", "voice_name": "en-us", "words_per_minute": 165},
        "research": {"providers": ["local_notes"]},
        "trends": {"providers": ["observations", "manual"]}}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_cli():
    """The engine's main.py, loaded by path: the repository root has its own `main` module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ttengine_cli", ENGINE / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_ctx(home: Path, overrides: dict | None = None) -> TikTokContext:
    notes = home / "research" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    for f in FIXTURE_NOTES.glob("*.yaml"):
        shutil.copy2(f, notes / f.name)
    return TikTokContext.create(home, overrides=_merge(FAST, overrides or {}), console_logging=False, load_env=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Tests must never pick up real credentials or safety overrides from the shell.
    for name in ("DRY_RUN", "AUTO_PUBLISH", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI",
                 "TIKTOK_HOME", "ANTHROPIC_API_KEY", "TTS_API_KEY", "YOUTUBE_API_KEY", "STUDIO_HOME"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path / "home")


@pytest.fixture
def researched(ctx):
    """ctx plus the Mandelbrot fixture topic researched and packaged."""
    from studio.research.topic_research import get_or_create_topic, research_topic
    from ttengine import packet
    tid = get_or_create_topic(ctx, "The Mandelbrot set")["topic_id"]
    research_topic(ctx, tid)
    pk = packet.build(ctx, tid)
    return ctx, tid, pk
