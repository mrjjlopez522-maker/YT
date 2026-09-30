# Shorts Studio — Architecture

Status: living document. Last updated 2026-09-30.

## 1. Purpose

Shorts Studio is an automated **content studio**, not a downloader or re-upload
tool. It takes a topic and produces an original YouTube Short: original
research, original script, original narration, original graphics and editing.
Licensed or public-domain footage supports the story; it is not the story.

It enforces three hard gates that cannot be bypassed from configuration:

1. **Rights gate:** every source used on screen or in the mix needs a verified
   rights record. If the rights are uncertain, the source is rejected.
2. **QC gate:** a failed QC check sets `NEEDS_REVISION` and stops the pipeline.
3. **Human gate:** uploads require an approval record. Public visibility,
   including scheduled go-live, requires an approval that explicitly allows
   public release. `DRY_RUN=true` and `AUTO_PUBLISH=false` are the defaults.

## 2. Environment findings (2026-09-30)

| Item | Finding | Consequence |
|---|---|---|
| Repository | Empty; no existing code | Nothing to preserve or reuse |
| OS / Python | Ubuntu 24.04, Python 3.11 | Target Python ≥ 3.11 |
| FFmpeg | Not preinstalled; installed 6.1.1 via apt (libx264, aac, libass, drawtext, loudnorm, blackdetect, silencedetect, sidechaincompress) | FFmpeg is the render engine |
| TTS | `espeak-ng` 1.51 installed; `libespeak-ng.so.1` exposes per-word timing callbacks (verified by prototype) | Offline TTS with real word-level timestamps; robotic voice quality, dev and test use only |
| Network | Only PyPI, apt, and Google APIs are reachable from the dev container. Wikipedia, Wikimedia Commons, Internet Archive, NASA, and LoC are blocked by the container egress policy | Network providers are implemented against documented APIs and tested with recorded-format fixtures, **not against live endpoints**. The end-to-end run uses offline providers |
| LLM | No API key in the environment | Offline script writer for the MVP; Anthropic provider is optional and needs `ANTHROPIC_API_KEY` |
| Web research | Web search available; direct page fetch blocked | YPP facts in `docs/BUSINESS_RESEARCH.md` come from search results and are marked for re-verification |

## 3. Module map

```
main.py                     CLI entry point (argparse); thin, delegates to studio.*
studio/
  config.py                 Load + validate config/settings.yaml and .env; safety invariants
  logging_setup.py          application/errors/render/api logs; secret redaction
  errors.py                 Exception hierarchy (retryable vs fatal)
  retry.py                  Retry with backoff; timeouts
  http.py                   Polite HTTP client: timeouts, backoff, honours 429 Retry-After, per-host pacing
  paths.py                  Workspace layout; deterministic file names
  ids.py / textutil.py      IDs, slugs, tokenisation, similarity primitives
  db/
    schema.sql              SQLite schema (explicit foreign keys)
    database.py             Connection, migrations, row helpers, status history
  research/
    providers.py            TopicResearchProvider: LocalNotes (offline), Wikipedia (network)
    topic_research.py       Collect research docs + atomic facts with citations
    trends.py               TrendProvider: WikipediaPageviews, YouTubeMostPopular, RSS, Manual
    niche.py                Niche Research Engine → data report (no ranking)
  sources/
    rights.py               License registry + policy engine (the rights gate)
    providers.py            SourceProvider: LocalLibrary, WikimediaCommons, InternetArchive, NASA
    discovery.py            Discover → verify → record evidence → ingest if permitted
    ingest.py               Copy/download approved media; probe; hash
    intelligence.py         Scene/black/motion analysis, watermark heuristic, transcript (STT abstraction)
    fixtures.py             Generates self-made CC0 test footage (Game of Life via FFmpeg)
  content/
    llm.py                  LLMProvider: Offline (none), Anthropic
    originality.py          Original Content Blueprint (format, angle, new value, standalone test)
    style.py                Anti-slop linter (banned openings, repetition, emoji, hype words)
    script.py               HOOK→SETUP→DEVELOPMENT→PAYOFF[→CTA]; 5 hooks + measurable scoring
    factcheck.py            Claims ↔ research facts; VERIFIED/NEEDS_REVIEW/UNVERIFIED/REJECTED
    metadata.py             5 titles, 3 descriptions, 10 keywords, 5 hashtag sets, 3 thumbnail concepts
  media/
    ffmpeg.py               ffmpeg/ffprobe wrappers (timeouts, render.log)
    tts.py                  TTSProvider: EspeakNG (local), ElevenLabs (network); pronunciation lexicon
    audio.py                VOICE/MUSIC/SFX/AMBIENCE tracks; loudnorm, ducking, limiter, silence detect
    captions.py             Word timings → readable chunks → ASS/SRT (styles in config/caption_styles.yaml)
    graphics.py             Pillow overlays: title/fact cards, timeline, highlight box, arrow, attribution
    storyboard.py           Scene plan with timing, visual choice, captions, transitions, graphics
    render.py               1080x1920 H.264/AAC assembly
    thumbnails.py           Thumbnail images for the 3 concepts
  qc/
    checks.py               18-point QC gate
    duplicates.py           Similarity across scripts/titles/topics/hooks/visual sequences/clips
  review/
    review.py               CLI review actions (APPROVE/REJECT/EDIT/RENDER_AGAIN/SCHEDULE)
    html.py                 Static review page + performance dashboard
  publish/
    youtube.py              Official YouTube Data API v3 upload (OAuth); DRY_RUN; privacy guards
  analytics/
    collector.py            YouTube Analytics API v2 snapshots; YouTube Studio CSV import
    experiments.py          Experiments with a minimum-sample guard and descriptive statistics
    costs.py                Cost ledger; COST_PER_VIDEO / per-100 / per-1000
    finance.py              Profitability model (actual data first; hypothetical scenarios labelled)
  pipeline/
    states.py               Content calendar state machine
    orchestrator.py         Stage runner with error capture, budget checks, daily volume limit
config/                     settings.yaml, caption_styles.yaml, style.yaml, niches.yaml, pricing.yaml, pronunciations.yaml
tests/                      pytest suite; fixtures generated locally (no copyrighted downloads)
```

Every provider family (research, trends, sources, LLM, TTS, STT, uploader)
sits behind a small interface class, so you can add providers without touching
the pipeline.

## 4. Pipeline and state machine

```
IDEA → RESEARCHING → SOURCING → SCRIPTING → EDITING → QC → REVIEW → APPROVED → SCHEDULED → PUBLISHED → ANALYZING
                                                        ↘ NEEDS_REVISION (QC fail)   ↘ REJECTED (human)
any stage → FAILED (error recorded; resumable)
```

Every transition is validated (`pipeline/states.py`) and written to
`status_history`. The stages are:

| Stage | Input | Output | Stops when |
|---|---|---|---|
| Research | topic | `research`, `research_facts` (each fact has a URL + title) | 0 facts → FAILED with guidance |
| Sourcing | topic keywords | `sources`, `licenses`, ingested media, analysis | No approved visual → graphics-only plan if `allow_graphics_only`, else FAILED |
| Scripting | facts, blueprint | `scripts`, `claims`, metadata | Unverifiable claims are removed and the script re-checked; hook/payoff invalid → NEEDS_REVISION |
| Editing | script | voice, captions, storyboard, scenes, render, thumbnails | FFmpeg error → FAILED (render.log) |
| QC | render + DB | `qc_report` | Any failed check → NEEDS_REVISION |
| Review | QC-passed video | `approvals` | Human decision only |
| Upload | APPROVED video | `uploads` | DRY_RUN writes the exact request instead of calling the API |
| Analytics | uploads | `analytics` snapshots | — |

## 5. Rights model (the legal gate)

Every source gets a `sources` row and a `licenses` row. The `source_rights`
view presents exactly the requested record fields: `source_id, source_url,
platform, creator, title, date_found, license_type, commercial_use_allowed,
modification_allowed, attribution_required, permission_reference,
permission_date, permission_notes, source_timestamps, rights_confidence`.

The policy engine (`sources/rights.py`) accepts a source only if **all** of
these hold:

- `license_type` is in the configured allow-list (default: `PD`, `PD-USGov`,
  `CC0-1.0`, `CC-BY-*`, `STOCK-LICENSED`, `USER-OWNED`, `WRITTEN-PERMISSION`).
- Commercial use is allowed **and** modification is allowed.
- The evidence that license type requires is present (for example, a stock
  license ID, a written-permission reference and date, or a raw API license
  field).
- `rights_confidence ≥ min_rights_confidence` (default 0.85). Confidence comes
  from the evidence type: machine-readable license metadata from an authoritative
  API scores higher than an uploader's free-text claim. **A high score is never
  treated as proof;** it is only a threshold for rejection.
- Otherwise the source is **REJECTED**, and the reasons are stored.

The policy handles these cases specifically:

- **Non-commercial (NC) and no-derivatives (ND) licenses:** always rejected.
- **Share-alike (SA) licenses:** rejected by default. A Short that adapts
  BY-SA footage would itself have to be licensed BY-SA.
- **"Standard YouTube License" and unknown or all-rights-reserved content:**
  always rejected.
- **Internet Archive items:** the license URL is asserted by the uploader, so
  confidence is capped below the default threshold and a human must confirm it
  (`verify-sources --approve ID --evidence ...`).

Every attribution string is carried into the on-screen credit and the
description.

**Text is copyrighted too:** Wikipedia prose is CC BY-SA. Research stores it
as evidence, but narration must be written in new words. QC measures n-gram
overlap between the script and every research and transcript text and fails
verbatim copying.

## 6. Originality model

For each video, `originality.py` produces a blueprint answering *"what new
information, explanation, perspective, story, or context do we add?"*:
`format` (EXPLAINER, TIMELINE, MYTH_VS_FACT, …), `angle`, `viewer_question`,
`new_value` items, planned graphics, and `standalone_test`. The blueprint also
sets measurable transformation limits that QC enforces:

- narration covers ≥ 85% of runtime
- no single continuous source shot longer than `max_continuous_source_seconds`
- source footage ≤ `max_source_screen_ratio` of runtime
- ≥ 1 original graphic

The blueprint holds a Short to those standards, but it does not make legal
judgements.

## 7. Data model (SQLite)

The tables and what they hold:

- **Core entities:** `channels`, `topics`, `research`, `research_facts`,
  `sources`, `licenses`, `scripts`, `claims`, `videos`, `scenes`, `assets`,
  `voices`.
- **Review and publishing:** `approvals`, `uploads`.
- **Measurement:** `analytics` (timestamped snapshots), `experiments`,
  `experiment_assignments`, `costs`, `revenue`.
- **Operations and audit:** `errors`, `status_history`, `niche_metrics`.

Foreign keys are explicit and enforced (`PRAGMA foreign_keys=ON`). Every video
traces through these links:

```
videos.topic_id → topics; videos.script_id → scripts → claims → research_facts → research
scenes.visual_source → sources → licenses;  assets.source_id → sources (music/SFX)
approvals / uploads / analytics / costs / experiment_assignments → videos
```

## 8. File layout and naming

These data directories live under the workspace root (`STUDIO_HOME`, default:
the repository root):

`database/ research/ sources/ licenses/ scripts/ audio/ visuals/ captions/ projects/ renders/ thumbnails/ exports/ analytics/ logs/`

The base name is deterministic: `{YYYY-MM-DD}_{topic-slug}_video-{NNN}`, for
example `2026-09-28_conways-game-of-life_video-001.mp4`. Source media is stored
as `sources/{source_id}/original.{ext}`, and license evidence as
`licenses/{source_id}.json`.

## 9. Safety invariants (enforced in code, covered by tests)

| Invariant | Where |
|---|---|
| `dry_run` defaults true; `auto_publish` defaults false; `manual_approval` defaults true | `config.py` |
| Public or scheduled-public upload requires an approval with `allow_public=1` | `publish/youtube.py` |
| No upload without an approval record when `manual_approval=true` | `publish/youtube.py` |
| Unverified rights → rejected, never used | `sources/rights.py`, `qc/checks.py` |
| Source audio is muted unless its rights allow audio reuse | `media/render.py` |
| No music unless `music_policy=licensed_library_only` and the track has an approved rights record | `media/audio.py`, QC |
| HTTP client honours 429/Retry-After; never rotates identities or evades limits | `http.py` |
| Secrets only from env; redacted in logs | `config.py`, `logging_setup.py` |

## 10. Scaling path (deliberately not built yet)

- **Now:** one machine, one SQLite database, synchronous stages.
- **Next:** `channels` already scopes topics and videos. Providers are lists in
  config, so multiple TTS providers and niches need no code change.
- **Later:** move the stage runner onto a job queue (SQLite-backed first, then
  Redis or RQ). Render workers pull `EDITING` jobs, and the database moves to
  Postgres when concurrent writers appear. None of this is built until the
  single-machine loop is producing videos that people watch.

## 11. What is tested vs. not

`README.md` holds the current matrix. The rule: a feature is "working" only if
a test or an end-to-end run exercised it in this environment. Network providers
are "implemented, contract-tested with recorded-format fixtures, not live-tested"
until someone runs them with network access.
