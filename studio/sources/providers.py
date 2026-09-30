"""Source discovery providers.

Each provider turns a search query into `SourceCandidate`s that carry the
license metadata *as the provider states it* plus the kind of evidence it is.
The rights engine (rights.py) makes the decision; providers never do.

Network providers use documented, public APIs through the polite HttpClient:
  * Wikimedia Commons   — MediaWiki API, imageinfo + extmetadata (structured license fields)
  * NASA Image and Video Library — images-api.nasa.gov (US Government work policy)
  * Internet Archive    — advancedsearch + metadata APIs (uploader-asserted licenses)
"""
from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import yaml

from ..errors import ProviderError
from ..http import HttpClient
from .rights import LicenseInfo, normalize_license

MEDIA_EXTS = {".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video", ".ogv": "video",
              ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
              ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".ogg": "audio", ".m4a": "audio"}


@dataclass
class SourceCandidate:
    source_url: str
    platform: str
    title: str
    media_type: str
    license: LicenseInfo
    creator: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    download_url: str | None = None
    local_path: str | None = None
    role: str = "visual"
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    source_timestamps: list = field(default_factory=list)


class SourceProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, limit: int) -> list[SourceCandidate]:
        ...

    def resolve_download(self, cand: SourceCandidate) -> str | None:
        return cand.download_url


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip() or None


def _matches(query: str, *fields: str) -> bool:
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    if not terms:
        return True
    hay = " ".join(f for f in fields if f).lower()
    return any(t in hay for t in terms)


# ---------------------------------------------------------------------------
class LocalLibraryProvider(SourceProvider):
    """Media you own or licensed, each described by a sidecar `<file>.rights.yaml`.

    Files without a sidecar are still reported (so you can see them) but carry
    license UNKNOWN and are therefore rejected by the rights gate.
    """
    name = "local_library"

    def __init__(self, library_dir: Path, *, role: str | None = None):
        self.library_dir = Path(library_dir)
        self.role = role

    def _sidecar(self, media: Path) -> dict | None:
        side = media.with_name(media.name + ".rights.yaml")
        if not side.is_file():
            return None
        try:
            return yaml.safe_load(side.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ProviderError(f"Unreadable rights sidecar {side}: {exc}") from exc

    def all(self) -> list[SourceCandidate]:
        out = []
        if not self.library_dir.is_dir():
            return out
        for media in sorted(self.library_dir.rglob("*")):
            kind = MEDIA_EXTS.get(media.suffix.lower())
            if not kind or not media.is_file():
                continue
            meta = self._sidecar(media)
            if meta is None:
                lic = LicenseInfo(license_type="UNKNOWN", evidence_kind="none",
                                  evidence={"note": "no rights sidecar found"})
                meta = {}
            else:
                lic = LicenseInfo(
                    license_type=normalize_license(meta.get("license_type"), meta.get("license_url")),
                    license_url=meta.get("license_url"),
                    commercial_use_allowed=meta.get("commercial_use_allowed"),
                    modification_allowed=meta.get("modification_allowed"),
                    attribution_required=meta.get("attribution_required"),
                    audio_reuse_allowed=bool(meta.get("audio_reuse_allowed", False)),
                    attribution_text=meta.get("attribution_text"),
                    creator=meta.get("creator"),
                    permission_reference=meta.get("permission_reference"),
                    permission_date=str(meta["permission_date"]) if meta.get("permission_date") else None,
                    permission_notes=meta.get("permission_notes"),
                    evidence_kind="human_verified" if meta.get("human_verified_by") else "manifest",
                    evidence={"sidecar": {k: (str(v) if not isinstance(v, (list, dict, bool, int, float)) else v)
                                          for k, v in meta.items()},
                              "description": meta.get("description", "")},
                )
            role = meta.get("role") or self.role or ("visual" if kind in ("video", "image") else "music")
            out.append(SourceCandidate(
                source_url=meta.get("source_url") or media.resolve().as_uri(), platform="local",
                title=meta.get("title") or media.stem, media_type=kind, license=lic,
                creator=meta.get("creator"), description=meta.get("description"),
                tags=list(meta.get("tags") or []), local_path=str(media), role=role,
                source_timestamps=list(meta.get("source_timestamps") or []),
            ))
        return out

    def search(self, query: str, limit: int) -> list[SourceCandidate]:
        # Files with no rights record always surface (and get rejected) so they are never silently ignored.
        hits = [c for c in self.all()
                if c.license.license_type == "UNKNOWN" or _matches(query, c.title, c.description or "", " ".join(c.tags))]
        return hits[:limit]


# ---------------------------------------------------------------------------
class WikimediaCommonsProvider(SourceProvider):
    name = "wikimedia_commons"
    API = "https://commons.wikimedia.org/w/api.php"

    def __init__(self, http: HttpClient, *, media: str = "video"):
        self.http = http
        self.media = media

    def search(self, query: str, limit: int) -> list[SourceCandidate]:
        search = f"filetype:{self.media} {query}" if self.media else query
        data = self.http.get_json(self.API, params={
            "action": "query", "format": "json", "formatversion": "2", "generator": "search",
            "gsrsearch": search, "gsrnamespace": "6", "gsrlimit": str(limit),
            "prop": "imageinfo", "iiprop": "url|size|mime|mediatype|extmetadata",
        })
        return [c for c in (self._candidate(p) for p in data.get("query", {}).get("pages", [])) if c]

    def _candidate(self, page: dict) -> SourceCandidate | None:
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            return None
        em = {k: (v or {}).get("value") for k, v in (info.get("extmetadata") or {}).items()}
        license_type = normalize_license(em.get("License") or em.get("LicenseShortName"), em.get("LicenseUrl"))
        creator = _strip_html(em.get("Artist"))
        credit = _strip_html(em.get("Credit"))
        mediatype = (info.get("mediatype") or "").upper()
        kind = "video" if mediatype == "VIDEO" else "audio" if mediatype == "AUDIO" else "image"
        attribution_required = str(em.get("AttributionRequired", "")).lower() == "true"
        title = page.get("title", "").removeprefix("File:")
        lic = LicenseInfo(
            license_type=license_type, license_url=em.get("LicenseUrl"),
            attribution_required=attribution_required, creator=creator,
            attribution_text=(f'"{title}" by {creator}, {em.get("LicenseShortName")}, via Wikimedia Commons'
                              if creator else None),
            evidence_kind="structured_api",
            evidence={"provider": "wikimedia_commons", "extmetadata": em, "description": _strip_html(em.get("ImageDescription")) or "",
                      "credit": credit or "", "restrictions": em.get("Restrictions") or "",
                      "usage_terms": em.get("UsageTerms") or ""},
        )
        return SourceCandidate(
            source_url=info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{quote(page.get('title', ''))}",
            platform="wikimedia_commons", title=title, media_type=kind, license=lic, creator=creator,
            description=_strip_html(em.get("ImageDescription")), download_url=info.get("url"),
            width=info.get("width"), height=info.get("height"), duration=info.get("duration"),
            tags=[t for t in (em.get("Categories") or "").split("|") if t],
        )


# ---------------------------------------------------------------------------
class NasaImagesProvider(SourceProvider):
    name = "nasa_images"
    API = "https://images-api.nasa.gov/search"

    def __init__(self, http: HttpClient, *, media_type: str = "video"):
        self.http = http
        self.media_type = media_type

    def search(self, query: str, limit: int) -> list[SourceCandidate]:
        data = self.http.get_json(self.API, params={"q": query, "media_type": self.media_type})
        items = data.get("collection", {}).get("items", [])[:limit]
        out = []
        for item in items:
            d = (item.get("data") or [{}])[0]
            nasa_id = d.get("nasa_id")
            if not nasa_id:
                continue
            credit = " ".join(filter(None, [d.get("photographer"), d.get("secondary_creator")]))
            lic = LicenseInfo(
                license_type="PD-USGov", license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
                creator=d.get("center") and f"NASA/{d.get('center')}" or "NASA",
                attribution_text=f"Footage: NASA{' / ' + d['center'] if d.get('center') else ''} ({nasa_id})",
                evidence_kind="agency_policy",
                evidence={"provider": "nasa_images", "nasa_id": nasa_id, "center": d.get("center"),
                          "description": d.get("description", ""), "credit": credit,
                          "policy_note": "NASA media is generally not copyrighted in the US; third-party material, "
                                         "logos and insignia have separate restrictions and must not imply endorsement."},
                risk_notes=["do not use NASA logos/insignia to imply endorsement"],
            )
            out.append(SourceCandidate(
                source_url=f"https://images.nasa.gov/details/{quote(nasa_id)}", platform="nasa_images",
                title=d.get("title") or nasa_id, media_type="video" if d.get("media_type") == "video" else "image",
                license=lic, creator=lic.creator, description=d.get("description"),
                tags=list(d.get("keywords") or []), download_url=item.get("href"),
            ))
        return out

    def resolve_download(self, cand: SourceCandidate) -> str | None:
        manifest = self.http.get_json(cand.download_url) if cand.download_url else []
        urls = [u for u in manifest if isinstance(u, str)]
        for suffix in ("~orig.mp4", "~large.mp4", "~medium.mp4", "~orig.jpg", "~large.jpg"):
            for u in urls:
                if u.endswith(suffix):
                    return u.replace("http://", "https://", 1)
        return None


# ---------------------------------------------------------------------------
class InternetArchiveProvider(SourceProvider):
    name = "internet_archive"
    SEARCH = "https://archive.org/advancedsearch.php"
    META = "https://archive.org/metadata/{identifier}"

    def __init__(self, http: HttpClient):
        self.http = http

    def search(self, query: str, limit: int) -> list[SourceCandidate]:
        data = self.http.get_json(self.SEARCH, params={
            "q": f"({query}) AND mediatype:movies AND licenseurl:*", "fl[]": ["identifier", "title", "creator",
                                                                              "licenseurl", "description", "subject"],
            "rows": str(limit), "output": "json",
        })
        out = []
        for doc in data.get("response", {}).get("docs", []):
            ident = doc.get("identifier")
            if not ident:
                continue
            lic_url = doc.get("licenseurl")
            creator = doc.get("creator") if isinstance(doc.get("creator"), str) else ", ".join(doc.get("creator") or [])
            desc = doc.get("description") if isinstance(doc.get("description"), str) else " ".join(doc.get("description") or [])
            lic = LicenseInfo(
                license_type=normalize_license(None, lic_url), license_url=lic_url, creator=creator or None,
                evidence_kind="uploader_asserted",
                evidence={"provider": "internet_archive", "identifier": ident, "licenseurl": lic_url,
                          "description": _strip_html(desc) or ""},
            )
            subjects = doc.get("subject") or []
            out.append(SourceCandidate(
                source_url=f"https://archive.org/details/{ident}", platform="internet_archive",
                title=doc.get("title") or ident, media_type="video", license=lic, creator=creator or None,
                description=_strip_html(desc), tags=subjects if isinstance(subjects, list) else [subjects],
                download_url=self.META.format(identifier=ident),
            ))
        return out

    def resolve_download(self, cand: SourceCandidate) -> str | None:
        meta = self.http.get_json(cand.download_url)
        ident = meta.get("metadata", {}).get("identifier")
        for f in meta.get("files", []):
            name = f.get("name", "")
            if name.lower().endswith(".mp4") and ident:
                return f"https://archive.org/download/{quote(ident)}/{quote(name)}"
        return None


def build_providers(ctx, names: list[str] | None = None) -> list[SourceProvider]:
    names = names or ctx.cfg.get("source_policy.providers")
    registry = {
        "local_library": lambda: LocalLibraryProvider(ctx.ws.home / "sources" / "library"),
        "wikimedia_commons": lambda: WikimediaCommonsProvider(ctx.http),
        "nasa_images": lambda: NasaImagesProvider(ctx.http),
        "internet_archive": lambda: InternetArchiveProvider(ctx.http),
    }
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise ProviderError(f"Unknown source providers in config: {unknown}")
    return [registry[n]() for n in names]
