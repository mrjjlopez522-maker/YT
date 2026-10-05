# Architecture

## Layers

```
Browser ──server actions / route handlers──► service.ts ──► Repo (MemoryRepo | PgRepo) ──► Postgres
   ▲                                             │
   └──── realtime "something changed" nudges ◄───┘ (demo: SSE from the server; live: Supabase Realtime + RLS)
```

- `src/lib/domain` is pure and shared with the browser: types, state machines, the topic tree, the keyword tagger and
  the matching function.
- `src/lib/server/service.ts` holds every business rule and authorization check. It's written once and runs on both
  repos, so the tests that prove its rules (races, privacy, moderation) run against memory *and* real Postgres.
- `Repo` is a tiny transactional interface (select/insert/update/delete/count inside `tx()`). `PgRepo` uses real
  transactions and `SELECT … FOR UPDATE`; `MemoryRepo` serialises transactions with a mutex and rolls back on error.
- Realtime events carry no data, only a topic (`user:<id>`, `session:<id>`); the page re-fetches through the server.

## State machines

Defined in `src/lib/domain/states.ts` and enforced again by triggers in `0002_rules_and_rls.sql`.

```
Request:     open → waiting → matched → closed
             open → async_open → answered → (waiting | closed)
             waiting → open (declined / expired / withdrawn / unavailable)
             open | waiting | async_open → cancelled
Invitation:  pending → accepted | declined | expired | cancelled | unavailable   (terminal)
Session:     scheduled → active → ended ;  scheduled → cancelled
Credential:  pending → verified | rejected ;  verified → revoked
Report:      open → actioned | dismissed
```

### Acceptance

`respondInvitation` runs in one transaction: lock the invitation and its request, re-check the deadline, lock both
people's profile rows in id order (prevents deadlocks and serialises a helper's concurrent accepts), re-check account
status, blocks and double-booking, then mark accepted, set the request to matched and create the session. Unique
indexes (`invitations_one_pending_per_request`, `sessions.request_id`) back this up. Expiry is processed lazily inside
the transactions that read invitations, and an accept after the deadline is treated as expired.

## Matching

`src/lib/domain/matching.ts`:

1. **Exclude** (never ranked): the requester, suspended/un-onboarded people, blocked in either direction, already invited
   for this request, no shared language, no shared format, no relevant topic experience, not actually available
   (presence expired, or weekly window doesn't cover the proposed time), or already busy. High-stakes topics match nobody.
2. **Score** the rest: topic closeness (40/30/15) + language (15 dialect / 10 base) + format preference (10/5) + availability
   (10) + welcomes beginners (8) + reviewed credential for that topic (5) + a bounded ±6 nudge from same-category feedback,
   applied only after 3+ ratings. Ties break by id. Reasons are generated alongside the score.

## Data model

See `supabase/migrations/0001_schema.sql`. Tables: profiles, topics, helper_topics, availability_windows,
credential_reviews, requests, invitations, async_responses, sessions, session_participants, messages, checklist_items,
shared_notes, private_notes (separate from shared on purpose), takeaways, feedback, blocks, reports, moderation_actions.
`src/lib/server/schema.ts` mirrors the columns; a test compares it with `information_schema`.
