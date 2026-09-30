import shutil

import pytest

from studio.errors import RightsError
from studio.sources import discovery, intelligence
from studio.sources.ingest import ingest
from studio.sources.providers import (InternetArchiveProvider, LocalLibraryProvider, NasaImagesProvider,
                                      WikimediaCommonsProvider)
from studio.sources.rights import LicenseInfo, evaluate, normalize_license

from .conftest import FakeHttp

POLICY = dict(allowed_licenses=["PD", "PD-USGov", "CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-SA-4.0",
                                "STOCK-LICENSED", "USER-OWNED", "WRITTEN-PERMISSION"],
              min_confidence=0.85)


@pytest.mark.parametrize("raw,url,expected", [
    ("CC BY-SA 4.0", None, "CC-BY-SA-4.0"),
    ("cc-by-4.0", None, "CC-BY-4.0"),
    (None, "https://creativecommons.org/licenses/by-nc/3.0/", "CC-BY-NC-3.0"),
    (None, "http://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
    (None, "http://creativecommons.org/publicdomain/mark/1.0/", "PD"),
    ("Public domain", None, "PD"),
    ("PD-USGov-NASA", None, "PD-USGov"),
    ("CC0", None, "CC0-1.0"),
    ("Standard YouTube License", None, "UNKNOWN"),
    (None, None, "UNKNOWN"),
])
def test_normalize_license(raw, url, expected):
    assert normalize_license(raw, url) == expected


def lic(**kw):
    base = dict(license_type="CC0-1.0", evidence_kind="structured_api", creator="Someone")
    base.update(kw)
    return LicenseInfo(**base)


def test_accepts_clean_cc0_and_cc_by():
    assert evaluate(lic(), **POLICY).accepted
    d = evaluate(lic(license_type="CC-BY-4.0"), **POLICY)
    assert d.accepted and d.attribution_required


@pytest.mark.parametrize("info,why", [
    (lic(license_type="CC-BY-NC-4.0"), "commercial"),
    (lic(license_type="CC-BY-ND-4.0"), "modification"),
    (lic(license_type="CC-BY-SA-4.0"), "share-alike"),
    (lic(license_type="UNKNOWN"), "unknown"),
    (lic(license_type="YOUTUBE-STANDARD"), "never reusable"),
    (lic(license_type="CC-BY-4.0", creator=None), "attribution"),
    (lic(license_type="STOCK-LICENSED", evidence_kind="manifest"), "reference"),
    (lic(license_type="WRITTEN-PERMISSION", evidence_kind="manifest", permission_reference="email 12"), "date"),
    (lic(evidence_kind="uploader_asserted"), "human verification"),
    (lic(license_type="CC-BY-NC-4.0", commercial_use_allowed=True), "does not permit"),
    (lic(license_type="PD-USGov", evidence_kind="agency_policy",
         evidence={"description": "Image courtesy of Getty Images"}), "below"),
    (lic(license_type="CC-BY-2.0"), "allowed_licenses"),
])
def test_rejections(info, why):
    d = evaluate(info, **POLICY)
    assert not d.accepted
    assert any(why in r for r in d.reasons), d.reasons


def test_share_alike_allowed_only_when_configured():
    assert evaluate(lic(license_type="CC-BY-SA-4.0"), **POLICY, allow_share_alike=True).accepted


def test_stock_license_with_reference_accepted():
    d = evaluate(lic(license_type="STOCK-LICENSED", evidence_kind="manifest", permission_reference="INV-2231",
                     permission_date="2026-09-01"), **POLICY)
    assert d.accepted and d.rights_confidence >= 0.95


# -- providers parse documented response formats ------------------------------
COMMONS = {"query": {"pages": [
    {"title": "File:Bridge.webm", "imageinfo": [{
        "url": "https://upload.wikimedia.org/x/Bridge.webm", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Bridge.webm",
        "mediatype": "VIDEO", "width": 1280, "height": 720, "duration": 12.5,
        "extmetadata": {"License": {"value": "cc-by-4.0"}, "LicenseShortName": {"value": "CC BY 4.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0"},
                        "Artist": {"value": "<a href='x'>Jane Doe</a>"}, "AttributionRequired": {"value": "true"},
                        "ImageDescription": {"value": "A bridge in wind"}}}]},
    {"title": "File:NC.webm", "imageinfo": [{
        "url": "https://upload.wikimedia.org/x/NC.webm", "mediatype": "VIDEO",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 2.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-nc/2.0"},
                        "Artist": {"value": "Bob"}}}]},
]}}

NASA = {"collection": {"items": [{"href": "https://images-assets.nasa.gov/video/X/collection.json",
                                  "data": [{"nasa_id": "X", "title": "Launch", "center": "KSC", "media_type": "video",
                                            "description": "Rocket launch", "keywords": ["launch"]}]}]}}

IA = {"response": {"docs": [{"identifier": "old_film", "title": "Old film", "creator": "Studio",
                             "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/"}]}}


def test_commons_provider_parses_structured_license():
    cands = WikimediaCommonsProvider(FakeHttp({"commons.wikimedia.org": COMMONS})).search("bridge", 5)
    assert [c.license.license_type for c in cands] == ["CC-BY-4.0", "CC-BY-NC-2.0"]
    assert cands[0].creator == "Jane Doe" and cands[0].license.evidence_kind == "structured_api"
    assert evaluate(cands[0].license, **POLICY).accepted
    assert not evaluate(cands[1].license, **POLICY).accepted


def test_nasa_and_internet_archive_providers():
    nasa = NasaImagesProvider(FakeHttp({"images-api.nasa.gov": NASA})).search("launch", 5)
    assert nasa[0].license.license_type == "PD-USGov" and evaluate(nasa[0].license, **POLICY).accepted
    ia = InternetArchiveProvider(FakeHttp({"archive.org": IA})).search("film", 5)
    d = evaluate(ia[0].license, **POLICY)
    assert ia[0].license.license_type == "PD" and not d.accepted  # uploader-asserted -> needs a human


def test_local_library_requires_sidecar(fixture_media, tmp_path):
    lib = tmp_path / "lib"
    shutil.copytree(fixture_media / "library", lib)
    (lib / "mystery.mp4").write_bytes((lib / "life_glider.mp4").read_bytes())
    cands = {c.title: c for c in LocalLibraryProvider(lib).all()}
    assert cands["mystery"].license.license_type == "UNKNOWN"
    assert not evaluate(cands["mystery"].license, **POLICY).accepted
    glider = next(c for c in cands.values() if "glider travelling" in c.title)
    assert evaluate(glider.license, **POLICY).accepted


# -- discovery end to end (offline library) -------------------------------------
def test_discovery_ingests_only_approved(ctx_with_library):
    ctx = ctx_with_library
    lib = ctx.ws.home / "sources" / "library"
    (lib / "unlicensed.mp4").write_bytes((lib / "life_glider.mp4").read_bytes())
    report = discovery.discover(ctx, queries=["game of life"])
    assert len(report.approved) == 4
    rejected_ids = [sid for sid, _ in report.rejected]
    assert len(rejected_ids) == 1
    bad = ctx.db.get("sources", rejected_ids[0])
    assert bad["status"] == "REJECTED" and "unknown" in bad["rejection_reason"]
    with pytest.raises(RightsError):
        ingest(ctx, rejected_ids[0])
    good = ctx.db.get("sources", report.approved[0])
    assert good["status"] == "INGESTED" and good["local_path"] and good["content_hash"]
    assert good["analysis_json"]["structured"]["HOOK_MOMENT"] is not None
    assert (ctx.ws.home / "licenses" / f"{good['source_id']}.json").exists()
    row = ctx.db.query("SELECT * FROM source_rights WHERE source_id = ?", (good["source_id"],))[0]
    assert row["license_type"] == "CC0-1.0" and row["rights_confidence"] >= 0.85


def test_provider_outage_is_reported_not_silent(ctx):
    report = discovery.discover(ctx, queries=["x"], providers=[WikimediaCommonsProvider(FakeHttp({}))])
    assert "wikimedia_commons" in report.provider_errors
    assert ctx.db.scalar("SELECT COUNT(*) FROM errors WHERE stage = 'discover-sources'") == 1


def test_human_verification_flow(ctx):
    report = discovery.discover(ctx, queries=["film"], providers=[InternetArchiveProvider(FakeHttp({"archive.org": IA}))],
                                ingest_approved=False)
    sid = report.rejected[0][0]
    discovery.human_verify(ctx, sid, reviewer="alex", approve=True, notes="Checked the film's copyright status")
    assert ctx.db.get("sources", sid)["status"] == "APPROVED"
    assert ctx.db.select("licenses", {"source_id": sid})[0]["verified_by"] == "human:alex"


def test_watermark_heuristic(fixture_media):
    from studio.media import ffmpeg
    frames, _ = ffmpeg.gray_frames(fixture_media / "watermarked.mp4", fps=4)
    assert intelligence.watermark_heuristic(frames)["status"] == "possible_watermark"
    frames, _ = ffmpeg.gray_frames(fixture_media / "library" / "life_random_soup.mp4", fps=4)
    assert intelligence.watermark_heuristic(frames)["status"] != "possible_watermark"
