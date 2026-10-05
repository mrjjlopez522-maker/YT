# People

**Someone knows. Meet them.**
Tell us what you need. Find someone who can help — by text, voice or video.

People connects someone with a question, curiosity or goal to a person who can help: ordinary people sharing lived
experience, and people with self-described professional experience (plus, where a moderator checked it, a credential
reviewed for one specific topic). Nobody is presented as always right, and medical, legal and investment advice is
deliberately not offered in this pilot.

This folder is a self-contained Next.js app. It is unrelated to the Python video tooling elsewhere in this repository.

## Run it now (demo mode, no accounts needed)

```bash
cd people
npm install
npm run dev            # http://localhost:3000
```

With no credentials the app runs in **demo mode**, which is labelled on every page:

- You pick a fictional sample person on the sign-in screen (Maya the learner, Omar and Priya as helpers, Chris as a
  new helper, Sam as a moderator), or create a new demo person and go through onboarding.
- Data lives in server memory, seeded from `src/lib/demo/fixtures.ts`, and resets on restart (or via **Setup → Reset demo data**).
- **Nobody real is on the other side.** Invitations are never auto-accepted. To see both sides, open a second (private)
  window, sign in as the helper, and accept from **Helping**. Messages, checklist and notes then update live between the two windows.
- Voice/video shows a "not set up" notice instead of a fake call.

## Run it for real (live mode)

Set Supabase variables (and optionally LiveKit) as described in [docs/SETUP.md](docs/SETUP.md), apply the migrations in
`supabase/migrations/`, then:

```bash
cp .env.example .env.local   # fill in values
npm run build && npm start
```

## Tests

| Command | What it covers |
| --- | --- |
| `npm test` | Domain + service tests on the in-memory repo: matching eligibility, blocking, acceptance races, expiry, private access, moderator permissions, call-token authorization, rate limits, async questions. Postgres tests are skipped unless `DATABASE_URL_TEST` is set. |
| `npm run test:db` | The **same service suite against real Postgres** with the real migrations (concurrent accepts use separate connections and row locks), plus database-level checks: state-transition triggers, append-only audit log, unique pending invitation, and row-level security as the `authenticated`/`anon` roles. Expects a disposable DB at `postgres://postgres:postgres@localhost:5432/people_test` (it drops and recreates `public`). |
| `npm run e2e` | Playwright against a production build in demo mode, desktop and phone: two browsers complete ask → invite → accept → chat → checklist → notes → end → wrap-up → My learning; outsider gets "Nothing here" and no call token; decline and no-match states; moderator-only dashboard; navigation. Run `npm run build` first. Set `CHROMIUM_PATH` to use a preinstalled Chromium. |
| `npm run check:secrets` | Builds with fake secret values and fails if any reach browser bundles. |
| `npm run typecheck`, `npm run lint` | TypeScript and ESLint. |

## What works

- **Home**: one focused question box, example prompts, four intent cards (Ask, Learn, Get moving, Explore), "Surprise me"
  (Explore topics drawn only from your own interests, checked against who is actually available), topic shortcuts.
- **Request creation**: question, suggested topic tags (deterministic keyword tagger; optional AI adapter) that you can
  correct with a category → subtopic → specific picker, intent, language, text/voice/video, now or a set time,
  experience level, context, at most one clarifying question, optional automatic matching.
- **Safety screening**: emergencies are never routed to volunteers (the person sees emergency-service guidance);
  medical/legal/investment topics are recognised and not matched.
- **Matching**: hard filters first (self, suspended, not onboarded, blocked either way, language, format, topic, actual
  availability, already busy/double-booked, already asked), then a small explainable score. Each match lists plain
  reasons ("Speaks Jordanian Arabic", "Welcomes beginners", "Available now for voice"). New helpers aren't penalised for
  having no feedback. The page states that ordering isn't a measure of expertise.
- **Invitations**: choose someone or match automatically (moves on to the next eligible person after a decline/expiry).
  One pending invitation per request; invitations expire (3 min for "now", up to 24 h for a set time). Waiting, declined,
  expired, withdrawn and unavailable states are all shown honestly. Sessions start only after the helper accepts;
  acceptance is transactional and re-checks blocks, suspension and double-booking under row locks.
- **No match**: leave the question for a written reply, propose a time, or widen format/topic — only with consent.
- **Session room**: question and agreed goal up top; realtime chat; intent-specific panels (Ask, Learn with steps and
  "Let me try", Get moving with goal + focus timer + check-in, Explore with optional prompts); shared checklist; shared
  notes and separate private notes; shared timer; mutual "Keep going"; end session; block; report. Voice/video through
  LiveKit when configured: mic only at first, camera only after both opt in (enforced in the token grant), mute, stop
  receiving the other person's media, leave, reconnect states.
- **Wrap-up**: was it addressed, private feedback (1–5, respectful, note only the other person sees), save agreed notes and
  next steps to **My learning** (user-edited, user-approved), mutual opt-in to reconnect and a follow-up request without
  exchanging contact details.
- **Profiles**: intro, "I can help with", "I'm curious about", languages, formats, location/time zone, experience per topic
  marked lived vs professional (self-described), reviewed credentials per topic, boundaries (can't-advise topics, session
  length), aggregate outcomes from completed sessions. Users can't verify themselves.
- **Helper inbox**: invitations with enough context to decide, one-tap accept/decline, "available now" that switches off
  by itself, upcoming sessions, questions waiting for a written answer, topic and weekly availability management.
- **Moderation**: open reports, evidence viewing (logged), resolve, suspend/reinstate with reasons, credential review
  (verify / reject / revoke per topic), append-only audit log.
- **Trust and privacy**: server-side authorization on every action, RLS on every table, rate limits (service + database
  backstop), no public indexing (`noindex` headers and metadata), no recording or transcription.

## Simulated or demo-only behaviour

- Demo personas replace real sign-in; the sample people, their availability, one past session, one credential review and
  one report are fixtures (`src/lib/demo/fixtures.ts`). They are never loaded in live mode.
- Demo realtime uses server-sent events from one server process; live mode uses Supabase Realtime.
- Nothing else is simulated: there are no fake calls, auto-replies, online counts, waiting times, verifications or payments.

## Needs credentials or more work before a real pilot

See [docs/SETUP.md](docs/SETUP.md) for configuration and [docs/TRUST_AND_SAFETY.md](docs/TRUST_AND_SAFETY.md) for
the safety model and its gaps. In short:

- **Not verified against a live Supabase project or LiveKit server in this environment** (no credentials here). The SQL,
  RLS and the production repository are tested on real Postgres 16; Supabase Auth, Supabase Realtime and LiveKit calls
  are written to their documented APIs but untested end to end.
- Age assurance is a self-declared checkbox — not robust. Invite-only sign-up is the main control for the pilot.
- No automated media moderation; LiveKit does not detect nudity or abuse. There is an integration boundary
  (call tokens are minted in one place, `src/lib/server/livekit.ts`) but no moderation service is connected.
- Rate limits are per user in the database; there's no IP-level or edge rate limiting.
- Matching loads candidates per category in memory — fine for a pilot, needs SQL-side filtering at scale.
- No email/push notifications for new invitations (helpers see them live in the app only).
- Not built (intentionally): payments, paid experts, credits, group rooms, translation, automated credential checks,
  recording/transcription, native apps.

## Project layout

```
src/lib/domain/     pure logic: types, state machines, topics, tagging, matching, prompts
src/lib/server/     service (all business rules + authorization), repos (memory, Postgres), auth, LiveKit, events
src/lib/ai/         optional categorization adapter (Anthropic), keyword fallback
src/lib/demo/       demo fixtures (demo mode only)
src/app/            routes: (app) signed-in pages, (public) sign-in/onboarding/setup/safety, api/ routes, actions.ts
src/components/     UI
supabase/migrations 0001 schema, 0002 rules + RLS + realtime, 0003 topics (generated by npm run gen:topics)
tests/              unit, db (Postgres), e2e (Playwright), shared service suite
docs/               setup, architecture, trust & safety
```
