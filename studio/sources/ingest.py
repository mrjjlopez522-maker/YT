"""Import approved media into the workspace. Refuses anything not rights-approved."""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from ..errors import RightsError
from ..media import ffmpeg
from ..textutil import now_iso, sha256_file


def ingest(ctx, source_id: str, *, provider=None) -> dict:
    src = ctx.db.require("sources", source_id)
    lic = ctx.db.select("licenses", {"source_id": source_id})
    if src["status"] not in ("APPROVED", "INGESTED") or not lic or lic[0]["verification_status"] != "VERIFIED":
        raise RightsError(f"Refusing to import {source_id}: rights are not verified (status {src['status']})")
    if src["status"] == "INGESTED" and src.get("local_path") and Path(src["local_path"]).exists():
        return src

    dest_dir = ctx.ws.source_dir(source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    origin = src.get("download_url") or src["source_url"]
    if src["platform"] in ("local", "generated"):
        local = Path(src["local_path"] or urlparse(src["source_url"]).path)
        dest = dest_dir / f"original{local.suffix.lower()}"
        if not dest.exists():
            shutil.copy2(local, dest)
    else:
        url = provider.resolve_download(_candidate_stub(src)) if provider else src.get("download_url")
        if not url:
            raise RightsError(f"No downloadable file found for {source_id}")
        suffix = Path(urlparse(url).path).suffix.lower() or ".bin"
        dest = dest_dir / f"original{suffix}"
        ctx.http.download(url, dest)
        origin = url

    info = ffmpeg.probe(dest) if src["media_type"] in ("video", "audio", "image") else None
    changes = {"local_path": str(dest), "content_hash": sha256_file(dest), "download_url": origin}
    if info:
        changes.update({"duration": info.duration or None, "width": info.width, "height": info.height,
                        "fps": info.fps, "has_audio": int(info.has_audio)})
    ctx.db.update("sources", source_id, changes)
    ctx.db.set_status("sources", source_id, "INGESTED", reason="media imported after rights verification")
    return ctx.db.require("sources", source_id)


class _Stub:
    def __init__(self, download_url):
        self.download_url = download_url


def _candidate_stub(src: dict):
    return _Stub(src.get("download_url"))
