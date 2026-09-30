import os
import shutil
from pathlib import Path

import pytest

from studio.context import StudioContext
from studio.sources import fixtures

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Tests must never pick up real credentials or safety overrides from the shell.
    for name in ("DRY_RUN", "AUTO_PUBLISH", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_API_KEY",
                 "ANTHROPIC_API_KEY", "TTS_API_KEY", "STUDIO_HOME"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def fixture_media(tmp_path_factory):
    """Generate the self-made CC0 Game of Life clips + notes once per test session."""
    root = tmp_path_factory.mktemp("fixture_media")
    fixtures.build_fixture_library(root / "library", root / "notes")
    fixtures.make_watermarked_clip(root / "watermarked.mp4")
    return root


class FakeHttp:
    """Stands in for HttpClient. `routes` maps a URL substring to a response (dict/list/str or callable)."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.request_count = 0

    def _match(self, url, params):
        self.calls.append((url, params))
        self.request_count += 1
        for key, value in self.routes.items():
            if key in url:
                return value(url, params) if callable(value) else value
        from studio.errors import NetworkBlockedError
        raise NetworkBlockedError(f"no fake route for {url}")

    def get_json(self, url, params=None, headers=None):
        return self._match(url, params)

    def get(self, url, params=None, headers=None, **kw):
        body = self._match(url, params)

        class R:
            text = body if isinstance(body, str) else ""
            status_code = 200
        return R()

    def post_json(self, url, json_body=None, headers=None):
        return self._match(url, json_body)

    def download(self, url, dest, max_bytes=0):
        raise AssertionError("tests must not download")


def make_ctx(home: Path, overrides=None, http=None) -> StudioContext:
    return StudioContext.create(home, config_path=REPO / "config" / "settings.yaml", overrides=overrides,
                                http=http or FakeHttp(), console_logging=False, load_env=False)


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path, overrides={"research": {"providers": ["local_notes"]},
                                      "source_policy": {"providers": ["local_library"]}})
    yield c
    c.close()


@pytest.fixture
def ctx_with_library(ctx, fixture_media):
    lib = ctx.ws.home / "sources" / "library"
    for f in (fixture_media / "library").iterdir():
        shutil.copy2(f, lib / f.name)
    notes = ctx.ws.home / "research" / "notes"
    for f in (fixture_media / "notes").iterdir():
        shutil.copy2(f, notes / f.name)
    return ctx
