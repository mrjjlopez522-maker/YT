import logging
import sqlite3
from datetime import date

import pytest

from studio.config import load_config
from studio.errors import ConfigError, NetworkBlockedError, ProviderError, RateLimitedError
from studio.http import HttpClient
from studio.logging_setup import redact, setup_logging
from studio.paths import is_valid_base_name, video_base_name
from studio.textutil import longest_common_run, numbers_in, slugify, text_similarity

from .conftest import REPO


def cfg(tmp_path, overrides=None):
    return load_config(tmp_path, config_path=REPO / "config" / "settings.yaml", overrides=overrides, load_env=False)


# -- config -----------------------------------------------------------------
def test_safe_defaults(tmp_path):
    c = cfg(tmp_path)
    assert c.dry_run is True
    assert c.auto_publish is False
    assert c.manual_approval is True
    assert c.auto_upload is False
    assert c.resolution == (1080, 1920)


def test_env_can_disable_dry_run_but_auto_publish_needs_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("AUTO_PUBLISH", "true")
    c = cfg(tmp_path)
    assert c.dry_run is False
    assert c.auto_publish is False  # config still says false
    c2 = cfg(tmp_path, {"publishing": {"auto_publish": True}})
    assert c2.auto_publish is True
    monkeypatch.setenv("AUTO_PUBLISH", "false")
    assert cfg(tmp_path, {"publishing": {"auto_publish": True}}).auto_publish is False


@pytest.mark.parametrize("override,fragment", [
    ({"production": {"target_duration": 42}}, "target_duration"),
    ({"production": {"video_resolution": [1920, 1080]}}, "9:16"),
    ({"publishing": {"default_privacy": "public"}}, "default_privacy"),
    ({"music": {"policy": "anything_goes"}}, "music.policy"),
    ({"source_policy": {"min_rights_confidence": 0.1}}, "min_rights_confidence"),
])
def test_invalid_config_rejected(tmp_path, override, fragment):
    with pytest.raises(ConfigError) as err:
        cfg(tmp_path, override)
    assert fragment in str(err.value)


def test_bad_boolean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "maybe")
    with pytest.raises(ConfigError):
        cfg(tmp_path)


# -- logging ------------------------------------------------------------------
def test_redaction(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecretvalue")
    text = "GET https://x/api?key=AIzaSyABCDEF&q=1 token sk-ant-supersecretvalue Authorization: Bearer abc.def"
    out = redact(text)
    assert "AIzaSyABCDEF" not in out and "sk-ant-supersecretvalue" not in out and "abc.def" not in out
    assert "q=1" in out


def test_log_files_created_and_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "very-secret-123")
    setup_logging(tmp_path, console=False)
    logging.getLogger("studio.api").info("calling with very-secret-123 and key=abcdef123")
    logging.getLogger("studio.render").error("render broke")
    for h in logging.getLogger("studio").handlers + logging.getLogger("studio.api").handlers:
        h.flush()
    for name in ("application.log", "errors.log", "render.log", "api.log"):
        assert (tmp_path / name).exists()
    api_log = (tmp_path / "api.log").read_text()
    assert "very-secret-123" not in api_log and "abcdef123" not in api_log
    assert "render broke" in (tmp_path / "errors.log").read_text()


# -- naming / text ---------------------------------------------------------------
def test_deterministic_file_names():
    name = video_base_name(date(2026, 9, 28), "topic-slug", 1)
    assert name == "2026-09-28_topic-slug_video-001"
    assert is_valid_base_name(name)
    assert slugify("Conway's Game of Life!") == "conways-game-of-life"
    with pytest.raises(ValueError):
        video_base_name(date(2026, 9, 28), "Bad Slug", 1)
    with pytest.raises(ValueError):
        video_base_name(date(2026, 9, 28), "ok", 1000)


def test_text_helpers():
    assert numbers_in("fifty dollars in 1,970 and 3.5") >= {"50", "1970", "3.5"}
    assert longest_common_run("the quick brown fox jumps", "a quick brown fox sat") == 3
    assert text_similarity("a glider moves across the grid", "a glider moves across the grid") == 1.0
    assert text_similarity("gliders and guns", "tax policy in spain") < 0.1


# -- database -------------------------------------------------------------------
def test_db_roundtrip_fk_and_history(ctx):
    db = ctx.db
    now = "2026-09-30T00:00:00+00:00"
    db.insert("topics", {"topic_id": "t1", "channel_id": ctx.cfg.channel_id, "topic": "X", "slug": "x",
                         "date_detected": now, "created_at": now, "updated_at": now,
                         "trend_evidence_json": {"a": [1, 2]}})
    assert db.get("topics", "t1")["trend_evidence_json"] == {"a": [1, 2]}
    with pytest.raises(sqlite3.IntegrityError):
        db.insert("topics", {"topic_id": "t2", "channel_id": "nope", "topic": "Y", "slug": "y",
                             "date_detected": now, "created_at": now, "updated_at": now})
    db.insert("sources", {"source_id": "s1", "source_url": "file:///a", "platform": "local", "date_found": now,
                          "media_type": "video", "status": "DISCOVERED", "updated_at": now})
    db.set_status("sources", "s1", "REJECTED", reason="test")
    hist = db.history("s1")
    assert hist[-1]["from_status"] == "DISCOVERED" and hist[-1]["to_status"] == "REJECTED"
    row = db.query("SELECT * FROM source_rights WHERE source_id = 's1'")[0]
    for col in ("source_url", "platform", "creator", "title", "date_found", "license_type", "commercial_use_allowed",
                "modification_allowed", "attribution_required", "permission_reference", "permission_date",
                "permission_notes", "source_timestamps", "rights_confidence"):
        assert col in row


def test_record_error_is_redacted(ctx, monkeypatch):
    monkeypatch.setenv("TTS_API_KEY", "tts-secret-999")
    err_id = ctx.db.record_error(stage="tts", exc=RuntimeError("failed with tts-secret-999"))
    assert "tts-secret-999" not in ctx.db.get("errors", err_id)["message"]


# -- http -----------------------------------------------------------------------
class _Resp:
    def __init__(self, status, headers=None, body=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body or {}
        self.text = str(body)
        self.url = "https://api.example.org/x"

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}

    def request(self, method, url, timeout=None, **kw):
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_http_honours_retry_after():
    sleeps = []
    s = _Session([_Resp(429, {"Retry-After": "3"}), _Resp(200, body={"ok": True})])
    client = HttpClient(session=s, sleep=sleeps.append, min_interval=0)
    assert client.get_json("https://api.example.org/x") == {"ok": True}
    assert 3.0 in sleeps


def test_http_refuses_excessive_retry_after():
    s = _Session([_Resp(429, {"Retry-After": "3600"})])
    client = HttpClient(session=s, sleep=lambda _: None, min_interval=0)
    with pytest.raises(RateLimitedError):
        client.get_json("https://api.example.org/x")


def test_http_network_blocked_and_server_errors():
    import requests
    client = HttpClient(session=_Session([requests.exceptions.ProxyError("403")]), sleep=lambda _: None, min_interval=0)
    with pytest.raises(NetworkBlockedError):
        client.get_json("https://blocked.example.org/")
    client = HttpClient(session=_Session([_Resp(503), _Resp(503), _Resp(200, body=[1])]), sleep=lambda _: None,
                        min_interval=0)
    assert client.get_json("https://api.example.org/x") == [1]
    client = HttpClient(session=_Session([_Resp(404)]), sleep=lambda _: None, min_interval=0)
    with pytest.raises(ProviderError):
        client.get_json("https://api.example.org/x")
