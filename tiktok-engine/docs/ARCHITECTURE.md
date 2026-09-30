# TikTok Engine — Architecture

Status: first-run prototype. Last updated 2026-09-30.

## 1. Environment inspection (2026-09-30)

| Item | Finding | Consequence |
|---|---|---|
| Repository | Contains **Shorts Studio** (`studio/`, 86 passing tests): rights engine, research, fact checking, script scoring, TTS with word timing, captions, audio mix, storyboard, FFmpeg renderer, QC gate, review, analytics, experiments, costs | Reused as the core library; the TikTok engine is a new application on top of it, not a fork |
| Tools | Python 3.11, FFmpeg 6.1 (libx264, libass, `mandelbrot`/`life`/`cellauto` sources), espeak-ng 1.51, Pillow, numpy | Procedural original visuals and audio can be made locally |
| Natural TTS | **Kokoro-82M** (Apache-2.0 weights) via `kokoro-onnx`; model files downloadable from GitHub releases; synthesis about 1.5x real time on 4 CPUs; **no word timings** | Local natural voice. Word timings come from our own forced aligner (espeak reference + MFCC DTW), which also aligns human recordings |
| TikTok APIs | `open.tiktokapis.com`, `www.tiktok.com`, `developers.tiktok.com` **blocked** by the dev container's network policy; no TikTok credentials | Content Posting / Display API clients are built against the documented contracts and tested with fakes; the live OAuth flow is not run |
| Trend data | TikTok Research API is academic-only (no commercial use). Creative Center has no official commercial API; third-party "APIs" are scrapers | Trends come from legitimate inputs: your recorded observations, Wikipedia pageviews, RSS, YouTube mostPopular, and our own TikTok analytics. No scraping |
| Credentials needed | `TIKTOK_CLIENT_KEY/SECRET` (posting and Display API), `YOUTUBE_*` (cross-posting), `ANTHROPIC_API_KEY` (LLM writer, optional), `TTS_API_KEY` (cloud TTS, optional), `RESEARCH_API_KEY` (reserved) | Everything else runs offline |

## 2. Reuse strategy

```
studio/        core library (unchanged behaviour; small backward-compatible hooks added)
tiktok-engine/ TikTok-first application
  main.py      CLI
  ttengine/    TikTok-specific modules
  config/      settings, brand, series, formats, caption styles, pricing, style rules
  fixtures/    research notes for the first video
  <data dirs>  database research trends sources licenses scripts audio visuals storyboards
               captions projects renders exports thumbnails analytics logs
```

The TikTok database schema is **the studio schema plus TikTok tables and
columns**, so studio modules work unchanged against it: research,
rights/discovery/ingest, fact checking, narration, captions, the audio mix,
render, and QC.

The TikTok layer adds:

- trends, format templates, idea batches, and research packets
- a TikTok script engine with hook types, template pacing, and comment prompts
- procedural original visuals, original music and SFX, and brand/series identity
- TikTok QC checks, the review page with cost and audit trail, the Content
  Posting API client, TikTok analytics with retention buckets, the content
  calendar, and generation modes

## 3. Pipeline

```
TREND DISCOVERY → TREND ANALYSIS (format templates) → IDEAS (batch, signals, eliminate)
→ TOPIC SELECTION → RESEARCH PACKET → SOURCES (licensed + original generated) → RIGHTS
→ ORIGINAL ANGLE (blueprint) → SCRIPT (hook types, template pacing, fact check)
→ VOICE (Kokoro/espeak/recording + alignment) → STORYBOARD → VISUAL ASSEMBLY → CAPTIONS
→ SOUND DESIGN (voice/music/sfx/ambience) → QC → HUMAN REVIEW → (dry-run) TIKTOK PUBLISH
→ ANALYTICS (snapshots, retention buckets) → CONTENT LEARNING → NEXT VIDEO
```

Calendar states:

- Main path: `IDEA → RESEARCH → SOURCE → SCRIPT → VOICE → EDIT → QC → REVIEW → APPROVED → SCHEDULED → PUBLISHED → ANALYTICS`
- Side states: `NEEDS_REVISION`, `REJECTED`, `FAILED` (with the failed stage recorded)

## 4. Key design decisions

1. **Original visuals are sources too.** Every generated visual is registered
   as a source with a self-generated CC0 rights record and its generator
   parameters. This covers fractal zooms, cellular automata, charts,
   timelines, coastline animations, and kinetic text. Every frame in a video
   therefore traces to a rights record, and "what original material was
   added" is answerable from the database. Generated visuals don't count
   against the third-party screen-time limit; third-party footage still does.
2. **Visual requirements live in research.** A fact in the research notes can
   carry a `visual` requirement (a generator and its parameters). The
   storyboard turns sentence → fact → visual. That is how an editor works
   from a researcher's packet.
3. **Format templates are editorial hypotheses, not measurements.** Each
   template (`config/formats.yaml`) records hook style, length, cut frequency,
   text density, narration style, visual style, story structure with time
   slots, comment prompt, payoff type, CTA style, and *why it works*. Its
   evidence label starts as ASSUMPTION. Analytics from our own videos and
   your recorded trend observations update per-template statistics. The
   engine never scrapes TikTok to "analyse formats".
4. **Signals are not predictions.** Idea scoring reports measurable
   characteristics (topic relevance, trend freshness, search demand, hook
   strength, story clarity, payoff strength, visual interest, novelty,
   feasibility, audience relevance), each with its evidence, and never a
   "virality score".
5. **Default length is 65 s** for monetizable formats: Creator Rewards needs
   videos of at least 1 minute (see `docs/BUSINESS_RESEARCH.md`). Shorter
   templates remain available for reach experiments.
6. **Publishing follows TikTok's rules.**
   - OAuth 2.0 with PKCE; the engine never asks for a password.
   - `creator_info` is queried first, and privacy must be chosen explicitly
     from the returned options, with no default.
   - Unaudited apps are limited to `SELF_ONLY`.
   - `DRY_RUN=true` and `AUTO_PUBLISH=false` are the defaults.
7. **Brand consistency without sameness.** The brand sets palette, fonts,
   caption style, voice, logo, music style, and graphic style. A series
   overrides accent, tag, intro, and outro. Individual videos vary format,
   visuals, and hook type, and duplicate detection guards the rest.

## 5. Audit trail

`python main.py audit --video ID` answers the ten audit questions from the
database:

1. Where did the information come from?
2. Where did the footage come from?
3. Was the footage legally usable?
4. What was changed?
5. What original material was added?
6. What sources support the claims?
7. How much did the video cost?
8. Was it approved?
9. Was it published?
10. How did it perform?

## 6. Not built in this first run (planned phases)

- **Cross-platform exports (phase 13):** YouTube Shorts via the existing
  `studio.publish.youtube`, Instagram Reels, and Facebook Reels, with
  platform-specific metadata.
- **Maps:** these need a licensed geodata source.
- **LLM-assisted idea generation and scripting at scale:** the Anthropic
  writer exists in `studio`; a TikTok prompt comes next.
- **Scheduled polling of analytics.**
- **OAuth token refresh:** re-run `python main.py auth` when the access token
  expires.
- **Linking an observed format trend to an evergreen topic.** For example,
  "fractal zooms are trending" does not yet boost the Mandelbrot topic
  automatically; you pick the topic.

## 7. First run result (2026-09-30)

`python main.py pipeline --trend-mode` found 3 trends:

- 1 observed format trend
- 2 manual evergreen ideas

Wikipedia pageviews were blocked by the development network, and that was
recorded as a provider error. The run then:

1. researched each trend topic; only the Mandelbrot set had research notes;
2. generated 20 ideas and eliminated 12, each with a recorded reason, such as
   "no researched hook" or "hook ~4.0 s to say, limit 3.6 s";
3. shortlisted 5 ideas;
4. produced 1 video, the daily limit.

The whole run took 4.5 minutes on 4 CPUs.

The video, `2026-09-30_the-mandelbrot-set_video-001`:

- **Length and format:** 68.7 s; H.264/AAC, 1080×1920.
- **Voice:** Kokoro `am_michael` at speed 1.1, calibrated at 164 wpm.
- **QC:** all 35 checks passed.
- **Audio:** -14.0 LUFS, true peak -1.6 dBTP.
- **Sources:** 12, all rights-verified.
- **Visuals:** 0% third-party footage; 10 distinct original visuals;
  2.47 visual changes per 10 s.
- **Hook:** spoken 0.17–1.91 s.
- **Payoff:** starts at 49.9 s.

Review found that the end card let the previous visual show through. The
backdrop is now opaque, and the video was re-rendered with
`review --render-again`, which is recorded in the audit trail.
