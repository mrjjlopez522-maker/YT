"""YouTube upload through the official YouTube Data API v3 only.

Safety rules, enforced here (not just in the CLI):
  * DRY_RUN (default true): the exact request is written to disk and recorded;
    nothing is sent. A live upload needs dry_run disabled in config or env.
  * An approval record is required (manual approval is the default).
  * Default privacy is private/unlisted. PUBLIC, or a scheduled go-live
    (publishAt), needs an approval that explicitly allows public release.
  * Automatic paths (auto_upload after approval) never publish publicly unless
    AUTO_PUBLISH is enabled.
OAuth tokens live in secrets/ (git-ignored), readable only by the owner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..errors import ApprovalRequiredError, ProviderError, ValidationError
from ..logging_setup import get_logger
from ..pipeline import states
from ..review.review import latest_approval
from ..textutil import new_id, now_iso

log = get_logger("studio.api")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]


def token_path(ctx) -> Path:
    return ctx.ws.home / "secrets" / "youtube_token.json"


def _clean_text(text: str) -> str:
    return (text or "").replace("<", "‹").replace(">", "›")


def _tags(keywords: list[str]) -> list[str]:
    out, total = [], 0
    for k in keywords:
        k = k.replace(",", " ").strip()
        cost = len(k) + (2 if " " in k else 0) + 1
        if k and total + cost <= 480:
            out.append(k)
            total += cost
    return out


def build_request_body(ctx, video: dict, *, privacy: str, publish_at: str | None) -> dict:
    title = _clean_text(video.get("selected_title") or "")[:100]
    if not title:
        raise ValidationError("Video has no title")
    description = _clean_text(video.get("selected_description") or "")
    if len(description.encode("utf-8")) > 5000:
        raise ValidationError("Description exceeds 5000 bytes")
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(ctx.cfg.get("publishing.made_for_kids")),
              "containsSyntheticMedia": bool(ctx.cfg.get("publishing.contains_synthetic_media"))}
    if publish_at:
        status["publishAt"] = publish_at
    return {"snippet": {"title": title, "description": description, "tags": _tags(video.get("tags_json") or []),
                        "categoryId": str(ctx.cfg.get("publishing.category_id")),
                        "defaultLanguage": ctx.cfg.get("channel.language"),
                        "defaultAudioLanguage": ctx.cfg.get("channel.language")},
            "status": status}


def plan_upload(ctx, video_id: str, *, privacy: str | None = None, explicit: bool = True) -> dict:
    """Decide what may be uploaded and how. Raises if the safety rules forbid it."""
    cfg = ctx.cfg
    v = ctx.db.require("videos", video_id)
    if v.get("qc_status") != "PASSED" or not v.get("render_path") or not Path(v["render_path"]).is_file():
        raise ApprovalRequiredError(f"{video_id} has no QC-passed render")
    approval = latest_approval(ctx, video_id)
    if v["status"] not in ("APPROVED", "SCHEDULED"):
        if cfg.manual_approval or v["status"] != "REVIEW":
            raise ApprovalRequiredError(f"{video_id} is {v['status']}; it must be APPROVED by a person before upload")
    if cfg.manual_approval and not approval:
        raise ApprovalRequiredError("No approval record found (manual approval is required)")
    privacy = privacy or cfg.get("publishing.default_privacy")
    if privacy not in ("private", "unlisted", "public"):
        raise ValidationError(f"Unknown privacy {privacy!r}")
    publish_at = None
    if v["status"] == "SCHEDULED":
        if not approval or not approval.get("scheduled_for"):
            raise ApprovalRequiredError("Scheduled video has no scheduled time on record")
        publish_at, privacy = approval["scheduled_for"], "private"  # the API requires private + publishAt
    goes_public = privacy == "public" or publish_at is not None
    if goes_public:
        if not approval or not approval.get("allow_public"):
            raise ApprovalRequiredError("Public release needs an approval with explicit public permission "
                                        "(review --approve --allow-public)")
        if not explicit and not cfg.auto_publish:
            raise ApprovalRequiredError("AUTO_PUBLISH is off: automatic uploads stay private/unlisted")
    return {"video": v, "approval": approval, "privacy": privacy, "publish_at": publish_at,
            "playlist_id": cfg.get("publishing.playlist_id") or None}


def credentials(ctx):
    """OAuth installed-app flow; the token is cached in secrets/ with owner-only permissions."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise ProviderError("Google API client libraries are not installed",
                            hint="pip install google-api-python-client google-auth-oauthlib") from exc
    path = token_path(ctx)
    creds = Credentials.from_authorized_user_file(str(path), SCOPES) if path.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        cid, secret = ctx.cfg.secret("YOUTUBE_CLIENT_ID"), ctx.cfg.secret("YOUTUBE_CLIENT_SECRET")
        if not cid or not secret:
            raise ProviderError("YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET are not set", hint="see .env.example")
        flow = InstalledAppFlow.from_client_config({"installed": {
            "client_id": cid, "client_secret": secret, "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}}, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(path, 0o600)
    return creds


def youtube_service(ctx):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials(ctx), cache_discovery=False)


def _execute_upload(service, body: dict, file_path: str) -> dict:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(file_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response, failures = None, 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as exc:
            status = getattr(exc.resp, "status", 0)
            if status in (500, 502, 503, 504) and failures < 5:
                failures += 1
                log.warning("upload chunk failed with %s; retrying (%d/5)", status, failures)
                continue
            raise ProviderError(f"YouTube upload failed: HTTP {status}") from exc
    return response


def upload(ctx, video_id: str, *, privacy: str | None = None, explicit: bool = True, live: bool = False,
           service=None) -> dict:
    plan = plan_upload(ctx, video_id, privacy=privacy, explicit=explicit)
    v = plan["video"]
    body = build_request_body(ctx, v, privacy=plan["privacy"], publish_at=plan["publish_at"])
    dry = ctx.cfg.dry_run or not live
    if live and ctx.cfg.dry_run:
        raise ApprovalRequiredError("DRY_RUN is enabled; set DRY_RUN=false (env) or publishing.dry_run: false to upload")
    out_dir = ctx.ws.export_dir(v["base_name"])
    out_dir.mkdir(parents=True, exist_ok=True)
    request = {"endpoint": "youtube.videos.insert", "part": "snippet,status", "body": body,
               "media_file": v["render_path"], "playlist_id": plan["playlist_id"]}
    (out_dir / "upload_request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    row = {"upload_id": new_id("upl"), "video_id": video_id,
           "approval_id": plan["approval"]["approval_id"] if plan["approval"] else None,
           "privacy_status": plan["privacy"], "publish_at": plan["publish_at"], "playlist_id": plan["playlist_id"],
           "dry_run": int(dry), "request_json": request, "created_at": now_iso()}
    if dry:
        ctx.db.insert("uploads", {**row, "status": "DRY_RUN"})
        log.info("DRY RUN upload for %s (privacy %s) written to %s", video_id, plan["privacy"], out_dir)
        return {**row, "status": "DRY_RUN"}

    service = service or youtube_service(ctx)
    try:
        response = _execute_upload(service, body, v["render_path"])
        yt_id = response["id"]
        if plan["playlist_id"]:
            service.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": plan["playlist_id"], "resourceId": {"kind": "youtube#video", "videoId": yt_id}}}).execute()
    except Exception as exc:
        ctx.db.insert("uploads", {**row, "status": "FAILED", "response_json": {"error": str(exc)}})
        ctx.db.record_error(stage="upload", exc=exc, video_id=video_id)
        raise
    ctx.db.insert("uploads", {**row, "status": "UPLOADED", "youtube_video_id": yt_id, "response_json": response})
    if plan["privacy"] in ("public", "unlisted") and not plan["publish_at"]:
        states.transition(ctx, video_id, "PUBLISHED", reason=f"uploaded as {plan['privacy']} ({yt_id})")
    log.info("uploaded %s -> https://youtu.be/%s (%s)", video_id, yt_id, plan["privacy"])
    return {**row, "status": "UPLOADED", "youtube_video_id": yt_id}


def mark_scheduled_published(ctx) -> list[str]:
    """Move SCHEDULED videos whose publish time has passed (and that were uploaded) to PUBLISHED."""
    moved = []
    for up in ctx.db.query("SELECT u.* FROM uploads u JOIN videos v ON v.video_id = u.video_id "
                           "WHERE v.status = 'SCHEDULED' AND u.status = 'UPLOADED' AND u.publish_at <= ?",
                           (now_iso(),)):
        states.transition(ctx, up["video_id"], "PUBLISHED", reason="scheduled publish time passed")
        moved.append(up["video_id"])
    return moved
