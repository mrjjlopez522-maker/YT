# TikTok Engine

A short-form media studio that researches, writes, voices, edits, and checks
original TikTok videos, then waits for a person to decide what to post.

It is built on the Shorts Studio core library (`../studio`). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and
[docs/BUSINESS_RESEARCH.md](docs/BUSINESS_RESEARCH.md) for verified platform and
monetization facts, kept separate from estimates and assumptions.

**The standard:** would this still be worth watching if the viewer had never
seen the source material? Every video is built from its own research, its own
script, and original visuals. Third-party footage is optional, needs a verified
rights record, and is capped by screen time.

## What it will not do

The engine will not:

- scrape TikTok
- bypass CAPTCHAs, DRM, or rate limits
- touch private accounts
- reuse or re-upload other creators' videos
- remove watermarks
- create fake likes, views, comments, or followers
- post anything by itself

If a source's rights are unclear, the source is rejected. The defaults are:

```
DRY_RUN=true    AUTO_PUBLISH=false    MANUAL_APPROVAL_REQUIRED=true
```

Publishing uses TikTok's official Content Posting API with OAuth (PKCE). The
engine never asks for your TikTok password.

## Quick start

```bash
# from the repository root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # plus: apt install ffmpeg espeak-ng
cd tiktok-engine
cp .env.example .env                        # optional keys; everything below runs offline
python main.py init
python main.py voice --download            # Kokoro-82M voice model (Apache-2.0, int8), ~115 MB
cp fixtures/notes/*.yaml research/notes/   # example research notes (the first video's topic)
python main.py pipeline --topic "The Mandelbrot set"
python main.py review --video <VIDEO_ID>   # opens the review page path; approve/reject/edit
```

Without the Kokoro model, set `voice.provider: espeak` in
`config/settings.yaml`. That voice is fully local but sounds robotic.

## Commands

| Command | What it does |
|---|---|
| `init` | Create the workspace and database, and show the safety switches |
| `niches` | Niche tradeoffs, measured where possible and labelled UNKNOWN otherwise. Deliberately no single "best" score |
| `trends [--discover]` | Active trends: the ones you observed (`config/trend_observations.yaml`) plus measured providers. Unmeasured signals stay empty |
| `formats [--analyze \| --update-stats]` | Format templates, and why they are expected to work (ASSUMPTION until our own data says otherwise) |
| `ideas --topic T [--topic T2] \| --from-trends \| --list \| --develop ID \| --produce ID` | Batch → eliminate (reason recorded) → shortlist → develop → produce |
| `research --topic T` | Research the topic and build the research packet (`research/<slug>/packet.md`) |
| `sources --topic T` | Licensed-source discovery through the rights gate |
| `verify [--approve ID \| --reject ID]` | Human rights verification |
| `script --topic T [--format F] [--duration N]` | Script preview: hook type, sections, fact check, promise check |
| `voice --list \| --download \| --calibrate \| --video ID` | Voice setup, speaking-rate calibration, narration |
| `storyboard --video ID` | Scene list: time, visual, narration, caption, transition, effect, SFX |
| `render --video ID` | Visuals, sound design, captions, and render, then QC |
| `qc --video ID` | Run the QC checklist again |
| `review [--video ID] [--approve [--allow-public] \| --reject \| --edit-caption T \| --render-again \| --schedule WHEN]` | The human decision |
| `auth [--code C --state S]` | TikTok OAuth (PKCE). The token is stored in `secrets/` with owner-only permissions |
| `publish --video ID [--privacy LEVEL] [--live]` | Dry-run plan by default. `--live` also needs `DRY_RUN=false`, an approval, and an OAuth token |
| `analytics --record ID --views N ... [--retention curve.csv] \| --import-csv F \| --fetch \| --compare ATTR` | Snapshots, retention buckets (0–2 / 2–5 / 5–10 / 10–20 / 20–30 / 30+ s), and descriptive comparisons |
| `experiments {create,list,assign,analyze}` | Vary one variable across different videos, with a minimum sample size |
| `calendar` | State board, next publishing slots, videos/day, and cost limit |
| `costs [--add-revenue USD --category C --start D --end D]` | COST_PER_VIDEO / 100 / 1000, REVENUE_PER_VIDEO, PROFIT_PER_VIDEO, and BREAK_EVEN, from recorded numbers only |
| `audit --video ID` | The ten audit questions, answered from the database |
| `pipeline --topic T [--format F] [--series S] [--mode M]` | One video, from research to review |
| `pipeline --trend-mode` | Trends → research → idea batch → shortlist → produce up to `ideas.produce` (and never more than `calendar.videos_per_day`) |
| `pipeline --resume ID [--from-stage S]` | Continue a failed or revised video |

Modes: `TREND_RESPONSE`, `EVERGREEN`, `SERIES`, `NEWS_EXPLAINER`, `SOURCE_INSPIRED`.

## How a video is made

1. **Research notes** (`research/notes/<slug>.yaml`) contain:
   - facts written in your own words, each cited, with optional `requires`
     (which fact must come first) and `visual` (which generator illustrates it)
   - typed hooks, quotes, locations, contradictions with resolutions, and
     comment prompts

   The packet must pass all of these checks before scripting:
   - enough facts
   - at least 2 independent sources
   - payoff material present
   - contradictions resolved
   - every fact cited

   See `fixtures/notes/the-mandelbrot-set.yaml`.
2. **Script.** The script has the sections HOOK / CONTEXT / DEVELOPMENT /
   PAYOFF.
   - The hook is one of 8 typed hooks, must be sayable in under 3.6 s by the
     real voice (the words-per-minute rate is measured, not assumed), and is
     checked for bait and fake urgency.
   - Every sentence is fact-checked against the research. Unsupported
     sentences are dropped.
   - The payoff must answer what the hook opened ("promise kept").
3. **Voice.** Kokoro (local, natural) or espeak. Word timings come from a
   forced aligner (espeak reference + MFCC + DTW), which also works on your
   own recordings.
4. **Edit.** Each sentence gets the visual its fact asks for:
   - Mandelbrot zooms, charts, timelines, Koch coastlines, space-filling
     curves, Game of Life, or kinetic text
   - a title card, a series tag, and an end card with the comment question
   - whooshes only at section changes
   - an original ambient music bed, ducked under the voice
   - word-timed captions inside the safe zone

   Every generated visual and sound is registered as a CC0 source that we
   made ourselves.
5. **QC.** The core QC checks plus the TikTok checks:
   - research packet
   - original editing
   - format pacing
   - promise kept
   - caption safe zone
   - no bait
   - AI-voice disclosure
   - caption length
   - audio rights
   - cost budget
   - standalone value

   A failure sets the video to `NEEDS_REVISION`.
6. **Review.** `exports/<video>/review.html` shows everything needed for the
   decision:
   - video, captions, post text, and hashtag sets
   - script, fact sources, and sources with licenses
   - cost, risk flags, QC results, and the audit trail

## Tested vs. not tested

| Area | Status |
|---|---|
| Research packet, script engine, fact check, hook typing, bait and urgency filters, promise check | Tested (unit + end-to-end) |
| Forced alignment | Tested: espeak at 175 wpm aligned to espeak at 135 wpm, median error under 60 ms (development measurement: about 5 ms). Also used with Kokoro in the first real video |
| Original visuals, music, and SFX as CC0 sources; rights gate; screen-time stats | Tested |
| Full pipeline to REVIEW (espeak voice), H.264/AAC 1080×1920 render, QC, review page, audit trail | Tested end-to-end |
| Kokoro voice | Used to render the first video (`pipeline --topic`, `pipeline --trend-mode`); not part of the automated tests, because it needs the model download |
| Trends (your observations, manual ideas), expiry, idea batches, signals | Tested offline |
| Wikipedia pageviews, Wikipedia research, RSS, and YouTube trend providers | Code from the studio core. **Not run here**: the development network blocks those hosts |
| Publishing: approval gate, dry-run plan, direct-post privacy rules, unaudited-app SELF_ONLY rule, chunking, PKCE | Tested, plus a live-mode run against a fake API client |
| Real TikTok OAuth, Content Posting API, and Display API calls | **Not tested**: no credentials, and TikTok hosts are blocked from the development environment. Built to the documented v2 contracts; verify with a sandbox app first |
| Token refresh | **Not built**: re-run `auth` when the token expires |
| TikTok Studio CSV import | Column names are tolerant guesses. **Not tested against a real export** |
| ElevenLabs voice, Anthropic LLM writer | In the core library; **not exercised here** |
| Cross-platform exports (phase 13), maps | **Not built** |

Run the tests from the repository root with `python -m pytest`. That runs the
studio suite and `tiktok-engine/tests`; the end-to-end test renders a real
video with espeak.

## Configuration

- `config/settings.yaml`: durations, calendar, voice, QC thresholds,
  publishing mode, and cost limits
- `config/brand.yaml` and `config/series.yaml`: identity
- `config/formats.yaml`: templates
- `config/caption_styles.yaml`, `config/style.yaml`: banned phrases, bait,
  fake urgency, and hook weights
- `config/pricing.yaml`

Secrets go only in `.env` (git-ignored). OAuth tokens go in `secrets/`
(git-ignored, mode 0600).
