"""TikTok publishing through the official Content Posting API only.

Rules enforced here:
  * OAuth 2.0 with PKCE; the engine never asks for or stores a password.
  * DRY_RUN (default true): the exact API plan is written to disk; nothing is sent.
  * A human approval record is required. Public visibility needs an approval
    with explicit public permission.
  * `creator_info` is queried first; privacy must be chosen explicitly (there is no
    default) and must be one of the returned `privacy_level_options`; interaction
    toggles disabled for the creator stay disabled.
  * Unaudited API clients may only post SELF_ONLY (TikTok's rule) — enforced unless
    publishing.tiktok_app_audited is true.
  * mode "draft" uses the Upload API (the video lands in the creator's TikTok inbox
    to finish in the app); mode "direct" uses Direct Post.
Endpoints follow TikTok for Developers documentation (v2); they were not called
live from the development environment.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import secrets
from pathlib import Path
from urllib.parse import urlencode

from studio.errors import ApprovalRequiredError, ProviderError, ValidationError
from studio.logging_setup import get_logger
from studio.textutil import new_id, now_iso
from . import states
from .review import latest_approval

log = get_logger("studio.api")
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API = "https://open.tiktokapis.com"
SCOPES = ["user.info.basic", "video.upload", "video.publish", "video.list"]
PRIVACY_LEVELS = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")
MIN_CHUNK, MAX_CHUNK = 5 * 1024 * 1024, 64 * 1024 * 1024


# -- OAuth (PKCE) -------------------------------------------------------------------------------
def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(client_key: str, redirect_uri: str, state: str, challenge: str, scopes=SCOPES) -> str:
    return AUTH_URL + "?" + urlencode({"client_key": client_key, "scope": ",".join(scopes), "response_type": "code",
                                       "redirect_uri": redirect_uri, "state": state, "code_challenge": challenge,
                                       "code_challenge_method": "S256"})


def exchange_code(session, *, client_key: str, client_secret: str, code: str, redirect_uri: str,
                  verifier: str) -> dict:
    resp = session.post(TOKEN_URL, data={"client_key": client_key, "client_secret": client_secret, "code": code,
                                         "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                                         "code_verifier": verifier},
                        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    data = resp.json()
    if "access_token" not in data:
        raise ProviderError(f"TikTok token exchange failed: {data.get('error')} {data.get('error_description')}")
    return data


def token_path(ctx) -> Path:
    return ctx.ws.home / "secrets" / "tiktok_token.json"


def save_token(ctx, token: dict) -> None:
    p = token_path(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(token), encoding="utf-8")
    os.chmod(p, 0o600)


# -- API client ------------------------------------------------------------------------------------
class TikTokAPI:
    def __init__(self, session, access_token: str):
        self.session, self.token = session, access_token

    def _post(self, path: str, body: dict) -> dict:
        resp = self.session.post(API + path, json=body, timeout=60, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json; charset=UTF-8"})
        data = resp.json()
        err = (data.get("error") or {})
        if err.get("code") not in (None, "ok"):
            raise ProviderError(f"TikTok API {path}: {err.get('code')} {err.get('message')}",
                                retryable=err.get("code") in ("rate_limit_exceeded", "internal_error"))
        return data.get("data") or {}

    def creator_info(self) -> dict:
        return self._post("/v2/post/publish/creator_info/query/", {})

    def init_direct(self, post_info: dict, source_info: dict) -> dict:
        return self._post("/v2/post/publish/video/init/", {"post_info": post_info, "source_info": source_info})

    def init_draft(self, source_info: dict) -> dict:
        return self._post("/v2/post/publish/inbox/video/init/", {"source_info": source_info})

    def upload(self, upload_url: str, path: Path, chunks: list[tuple[int, int]]) -> None:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            for first, last in chunks:
                fh.seek(first)
                resp = self.session.put(upload_url, data=fh.read(last - first + 1), timeout=300, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(last - first + 1),
                    "Content-Range": f"bytes {first}-{last}/{size}"})
                if resp.status_code not in (200, 201, 206):
                    raise ProviderError(f"chunk {first}-{last} upload failed: HTTP {resp.status_code}", retryable=True)

    def status(self, publish_id: str) -> dict:
        return self._post("/v2/post/publish/status/fetch/", {"publish_id": publish_id})


def chunk_plan(size: int, chunk_size: int = 10 * 1024 * 1024) -> tuple[dict, list[tuple[int, int]]]:
    """Media transfer rules: files under 5 MB go in one chunk; otherwise chunks of 5-64 MB, the
    remainder merged into the last chunk (total_chunk_count = floor(size / chunk_size))."""
    if size < MIN_CHUNK:
        return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}, [(0, size - 1)]
    chunk_size = max(MIN_CHUNK, min(MAX_CHUNK, chunk_size))
    count = max(1, size // chunk_size)
    chunks = [(i * chunk_size, (i + 1) * chunk_size - 1) for i in range(count - 1)]
    chunks.append(((count - 1) * chunk_size, size - 1))
    return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}, chunks


# -- publishing ----------------------------------------------------------------------------------------
def plan(ctx, video_id: str, *, privacy_level: str | None, disable_comment: bool = False, disable_duet: bool = False,
         disable_stitch: bool = False, creator: dict | None = None) -> dict:
    cfg = ctx.cfg
    v = ctx.db.require("videos", video_id)
    if v.get("qc_status") != "PASSED" or not v.get("render_path") or not Path(v["render_path"]).is_file():
        raise ApprovalRequiredError(f"{video_id} has no QC-passed render")
    if v["status"] not in ("APPROVED", "SCHEDULED"):
        raise ApprovalRequiredError(f"{video_id} is {v['status']}; a person must approve it first")
    approval = latest_approval(ctx, video_id)
    if not approval:
        raise ApprovalRequiredError("No approval record found")
    mode = cfg.get("publishing.tiktok_mode")
    if mode == "direct":
        if not privacy_level:
            raise ValidationError("Choose the privacy level explicitly (TikTok requires a manual choice, no default): "
                                  + ", ".join(PRIVACY_LEVELS))
        if privacy_level not in PRIVACY_LEVELS:
            raise ValidationError(f"Unknown privacy level {privacy_level!r}")
        if creator and privacy_level not in (creator.get("privacy_level_options") or []):
            raise ValidationError(f"{privacy_level} is not offered for this creator: {creator.get('privacy_level_options')}")
        if privacy_level != "SELF_ONLY" and not cfg.get("publishing.tiktok_app_audited", False):
            raise ApprovalRequiredError("Unaudited TikTok API clients can only post SELF_ONLY; pass the TikTok app "
                                        "audit and set publishing.tiktok_app_audited: true")
        if privacy_level == "PUBLIC_TO_EVERYONE" and not approval.get("allow_public"):
            raise ApprovalRequiredError("Public posting needs an approval with explicit public permission")
    caption = v.get("caption") or v.get("selected_title") or ""
    if len(caption) > int(cfg.get("publishing.max_caption_chars")):
        raise ValidationError("Caption is longer than publishing.max_caption_chars")
    md = v.get("metadata_json") or {}
    size = Path(v["render_path"]).stat().st_size
    source_info, chunks = chunk_plan(size)
    post_info = None
    if mode == "direct":
        creator = creator or {}
        post_info = {"title": caption, "privacy_level": privacy_level,
                     "disable_comment": bool(disable_comment or creator.get("comment_disabled")),
                     "disable_duet": bool(disable_duet or creator.get("duet_disabled")),
                     "disable_stitch": bool(disable_stitch or creator.get("stitch_disabled")),
                     "video_cover_timestamp_ms": int(md.get("cover_timestamp_ms", 1000))}
        max_dur = creator.get("max_video_post_duration_sec")
        if max_dur and float(v["duration"]) > float(max_dur):
            raise ValidationError(f"Video is {v['duration']:.0f}s; this creator can post up to {max_dur}s")
    return {"video": v, "approval": approval, "mode": mode, "post_info": post_info, "source_info": source_info,
            "chunks": chunks, "caption": caption}


def publish(ctx, video_id: str, *, privacy_level: str | None = None, live: bool = False, api: TikTokAPI | None = None,
            **toggles) -> dict:
    dry = ctx.cfg.dry_run or not live
    if live and ctx.cfg.dry_run:
        raise ApprovalRequiredError("DRY_RUN is enabled; set DRY_RUN=false (env) or publishing.dry_run: false")
    creator = api.creator_info() if (api and not dry) else None
    p = plan(ctx, video_id, privacy_level=privacy_level, creator=creator, **toggles)
    v = p["video"]
    request = {"mode": p["mode"], "creator_info_first": "POST /v2/post/publish/creator_info/query/",
               "init": ("POST /v2/post/publish/video/init/" if p["mode"] == "direct"
                        else "POST /v2/post/publish/inbox/video/init/"),
               "post_info": p["post_info"], "source_info": p["source_info"],
               "chunks": [f"bytes {a}-{b}" for a, b in p["chunks"]], "file": v["render_path"],
               "status_poll": "POST /v2/post/publish/status/fetch/"}
    out = ctx.ws.export_dir(v["base_name"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "tiktok_publish_plan.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    row = {"upload_id": new_id("upl"), "video_id": video_id, "approval_id": p["approval"]["approval_id"],
           "platform": "tiktok", "privacy_status": privacy_level or ("DRAFT" if p["mode"] == "draft" else "UNSET"),
           "dry_run": int(dry), "request_json": request, "caption": p["caption"], "created_at": now_iso()}
    if dry:
        ctx.db.insert("uploads", {**row, "status": "DRY_RUN"})
        return {**row, "status": "DRY_RUN"}
    if api is None:
        raise ProviderError("Live publishing needs an authorised TikTok API client (python main.py auth)")
    try:
        init = api.init_direct(p["post_info"], p["source_info"]) if p["mode"] == "direct" else \
            api.init_draft(p["source_info"])
        api.upload(init["upload_url"], Path(v["render_path"]), p["chunks"])
        status = api.status(init["publish_id"])
    except Exception as exc:
        ctx.db.insert("uploads", {**row, "status": "FAILED", "response_json": {"error": str(exc)}})
        ctx.db.record_error(stage="publish", exc=exc, video_id=video_id)
        raise
    # TikTok returns the live post id in `publicaly_available_post_id` (sic) once processing completes
    post_ids = status.get("publicaly_available_post_id") or []
    ctx.db.insert("uploads", {**row, "status": "UPLOADED", "publish_id": init["publish_id"], "publish_time": now_iso(),
                              "youtube_video_id": str(post_ids[0]) if post_ids else None, "response_json": status})
    if p["mode"] == "direct" and privacy_level != "SELF_ONLY":
        states.transition(ctx, video_id, "PUBLISHED", reason=f"TikTok direct post ({privacy_level})")
    return {**row, "status": "UPLOADED", "publish_id": init["publish_id"], "tiktok_status": status}
