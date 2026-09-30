"""The rights gate.

Decides whether a source may be used, from its license metadata and the
evidence behind it. The engine is conservative by construction:

  * unknown / missing / conflicting information  -> REJECT
  * NC or ND licenses                            -> REJECT (monetised, edited use)
  * share-alike                                  -> REJECT unless explicitly allowed
  * attribution required but nobody to credit    -> REJECT
  * confidence below the configured threshold    -> REJECT

`rights_confidence` reflects how strong the *evidence* is. It is a threshold
for rejection, never proof of legal ownership. Nothing here is legal advice.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# evidence kinds and the starting confidence each can support
EVIDENCE_CONFIDENCE = {
    "human_verified": 0.97,      # a person checked the license/permission and recorded it
    "manifest_reference": 0.95,  # user rights manifest with a concrete permission reference
    "structured_api": 0.90,      # machine-readable license field from a curated archive (e.g. Commons)
    "agency_policy": 0.88,       # government agency media policy (e.g. NASA) — third-party content possible
    "manifest": 0.80,            # user manifest without a reference
    "uploader_asserted": 0.60,   # free-form uploader claim (e.g. Internet Archive licenseurl)
    "none": 0.0,
}


@dataclass(frozen=True)
class LicenseTerms:
    commercial: bool
    modification: bool
    attribution: bool
    share_alike: bool = False
    requires_reference: bool = False   # a permission/licence reference must be recorded
    requires_date: bool = False


REGISTRY: dict[str, LicenseTerms] = {
    "PD": LicenseTerms(True, True, False),
    "PD-USGov": LicenseTerms(True, True, False),
    "CC0-1.0": LicenseTerms(True, True, False),
    "STOCK-LICENSED": LicenseTerms(True, True, False, requires_reference=True, requires_date=True),
    "USER-OWNED": LicenseTerms(True, True, False, requires_reference=True),
    "WRITTEN-PERMISSION": LicenseTerms(True, True, False, requires_reference=True, requires_date=True),
}
for _v in ("1.0", "2.0", "2.5", "3.0", "4.0"):
    REGISTRY[f"CC-BY-{_v}"] = LicenseTerms(True, True, True)
    REGISTRY[f"CC-BY-SA-{_v}"] = LicenseTerms(True, True, True, share_alike=True)
    REGISTRY[f"CC-BY-ND-{_v}"] = LicenseTerms(True, False, True)
    REGISTRY[f"CC-BY-NC-{_v}"] = LicenseTerms(False, True, True)
    REGISTRY[f"CC-BY-NC-SA-{_v}"] = LicenseTerms(False, True, True, share_alike=True)
    REGISTRY[f"CC-BY-NC-ND-{_v}"] = LicenseTerms(False, False, True)

ALWAYS_REJECT = {"UNKNOWN", "ALL-RIGHTS-RESERVED", "YOUTUBE-STANDARD", "FAIR-USE-CLAIM", "EDITORIAL-ONLY"}

_CC_URL = re.compile(r"creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/(\d\.\d)", re.I)
_THIRD_PARTY = re.compile(r"(©|\(c\)|copyright|courtesy of|getty|reuters|associated press|\bap photo\b|all rights reserved)", re.I)


def normalize_license(raw: str | None, url: str | None = None) -> str:
    """Map license names/URLs from many providers onto registry ids. Unknown -> 'UNKNOWN'."""
    if url:
        m = _CC_URL.search(url)
        if m:
            kind, code, ver = m.group(1).lower(), m.group(2).lower(), m.group(3)
            if kind == "publicdomain":
                return "CC0-1.0" if code == "zero" else "PD" if code == "mark" else "UNKNOWN"
            return f"CC-{code.upper()}-{ver}"
    if not raw:
        return "UNKNOWN"
    s = re.sub(r"[\s_]+", "-", raw.strip()).upper()
    if s in REGISTRY or s in ALWAYS_REJECT:
        return s
    if s in {"CC0", "CC-ZERO", "CC0-1", "CC-0"}:
        return "CC0-1.0"
    if s.startswith("PD-USGOV") or s in {"PD-US-GOV", "US-GOVERNMENT-WORK"}:
        return "PD-USGov"
    if s in {"PD", "PUBLIC-DOMAIN", "PUBLIC-DOMAIN-MARK", "PDM", "PD-OLD", "NO-KNOWN-COPYRIGHT-RESTRICTIONS"} \
            or s.startswith("PD-OLD") or s.startswith("PD-ART"):
        return "PD"
    m = re.match(r"^CC-?(BY(?:-NC)?(?:-SA|-ND)?)-?(\d(?:\.\d)?)", s)
    if m:
        ver = m.group(2) if "." in m.group(2) else f"{m.group(2)}.0"
        return f"CC-{m.group(1)}-{ver}"
    return "UNKNOWN"


@dataclass
class LicenseInfo:
    license_type: str
    license_url: str | None = None
    commercial_use_allowed: bool | None = None
    modification_allowed: bool | None = None
    attribution_required: bool | None = None
    audio_reuse_allowed: bool = False
    attribution_text: str | None = None
    creator: str | None = None
    permission_reference: str | None = None
    permission_date: str | None = None
    permission_notes: str | None = None
    evidence_kind: str = "none"
    evidence: dict = field(default_factory=dict)
    risk_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RightsDecision:
    accepted: bool
    license_type: str
    rights_confidence: float
    commercial_use_allowed: bool
    modification_allowed: bool
    attribution_required: bool
    share_alike: bool
    reasons: list[str]

    @property
    def status(self) -> str:
        return "VERIFIED" if self.accepted else "REJECTED"


def evaluate(info: LicenseInfo, *, allowed_licenses: list[str], min_confidence: float,
             allow_share_alike: bool = False) -> RightsDecision:
    reasons: list[str] = []
    lt = info.license_type or "UNKNOWN"
    terms = REGISTRY.get(lt)

    if lt in ALWAYS_REJECT or terms is None:
        reasons.append(f"license '{lt}' is unknown or never reusable")
        return RightsDecision(False, lt, 0.0, False, False, True, False, reasons)

    # The registry is authoritative about what a license permits; claims that
    # contradict it are a red flag, not an override.
    for claimed, actual, label in ((info.commercial_use_allowed, terms.commercial, "commercial use"),
                                   (info.modification_allowed, terms.modification, "modification")):
        if claimed is True and actual is False:
            reasons.append(f"metadata claims {label} is allowed but {lt} does not permit it")
    if not terms.commercial:
        reasons.append(f"{lt} does not allow commercial use")
    if not terms.modification:
        reasons.append(f"{lt} does not allow modification")
    if terms.share_alike and not allow_share_alike:
        reasons.append(f"{lt} is share-alike: the finished Short would have to carry the same license")
    if lt not in allowed_licenses:
        reasons.append(f"{lt} is not in source_policy.allowed_licenses")
    if terms.requires_reference and not (info.permission_reference or "").strip():
        reasons.append(f"{lt} requires a permission/licence reference (e.g. invoice or licence id)")
    if terms.requires_date and not (info.permission_date or "").strip():
        reasons.append(f"{lt} requires the permission/licence date")
    if terms.attribution and not ((info.attribution_text or "").strip() or (info.creator or "").strip()):
        reasons.append("attribution is required but no creator/attribution text is known")

    confidence = EVIDENCE_CONFIDENCE.get(info.evidence_kind, 0.0)
    if info.evidence_kind == "manifest" and (info.permission_reference or "").strip():
        confidence = EVIDENCE_CONFIDENCE["manifest_reference"]
    haystack = " ".join(str(info.evidence.get(k, "")) for k in ("description", "credit", "restrictions", "usage_terms"))
    if _THIRD_PARTY.search(haystack) and lt in {"PD", "PD-USGov", "CC0-1.0"}:
        confidence -= 0.25
        info.risk_notes.append("description/credit mentions a third-party rights holder")
    if info.evidence.get("restrictions"):
        confidence -= 0.05
        info.risk_notes.append(f"restrictions noted: {info.evidence.get('restrictions')}")
    confidence = round(max(0.0, min(1.0, confidence)), 3)
    if confidence < min_confidence:
        reasons.append(f"rights confidence {confidence:.2f} is below the required {min_confidence:.2f}"
                       + (" — uploader-asserted licenses need human verification (verify-sources --approve)"
                          if info.evidence_kind == "uploader_asserted" else ""))

    return RightsDecision(accepted=not reasons, license_type=lt, rights_confidence=confidence,
                          commercial_use_allowed=terms.commercial, modification_allowed=terms.modification,
                          attribution_required=terms.attribution, share_alike=terms.share_alike,
                          reasons=reasons or ["all rights checks passed"])


def attribution_line(license_type: str, creator: str | None, title: str | None, attribution_text: str | None) -> str:
    if attribution_text:
        return attribution_text
    who = creator or "unknown creator"
    what = f'"{title}"' if title else "footage"
    return f"{what} by {who}, {license_type}"
