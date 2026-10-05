# Setup guide

The app picks its mode at startup:

| Mode | When | Accounts | Data | Realtime |
| --- | --- | --- | --- | --- |
| Demo | Supabase variables missing, or `PEOPLE_MODE=demo` | Sample personas (cookie) | Server memory, fixtures | Server-sent events |
| Live | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` and `DATABASE_URL` set | Supabase Auth (email link) | Supabase Postgres | Supabase Realtime |

`/setup` in the app shows what's configured.

## 1. Supabase

1. **Create a project** at supabase.com.
2. **Apply the migrations** in order — `supabase/migrations/0001_schema.sql`, `0002_rules_and_rls.sql`, `0003_topics.sql`:
   - with the Supabase CLI: `supabase link --project-ref <ref>` then `supabase db push`, or
   - paste each file into the SQL editor and run it.
   `0002` adds the session and inbox tables to the existing `supabase_realtime` publication.
3. **Auth → Providers → Email**: keep Email enabled. For an invite-only pilot, turn off "Allow new users to sign up",
   set `PEOPLE_INVITE_ONLY=true`, and invite people from **Authentication → Users → Invite user**.
4. **Auth → URL configuration**: set the Site URL to your app's URL and add `https://<your-app>/auth/callback`
   (and `http://localhost:3000/auth/callback` for local work) to Redirect URLs.
5. **Environment variables** (Project Settings → API and the **Connect** dialog):
   - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` — public by design; every table is protected by RLS.
   - `DATABASE_URL` — server-only. Use the **session pooler** or direct connection string. It's used for all writes,
     inside transactions with row locks. Never expose it with a `NEXT_PUBLIC_` prefix.
   - `DATABASE_CA_CERT` — paste Supabase's root certificate (Database settings → SSL configuration) to get verified TLS.
     If you use it, don't add `sslmode` to `DATABASE_URL`.
   The app never needs the `service_role` key.
6. **Make someone a moderator** (after they've signed in and finished onboarding):
   ```sql
   update public.profiles set role = 'moderator' where id = '<auth user id>';
   ```
   Moderator status is only ever changed in the database; the app has no way to self-promote.

### How access is enforced

- Browsers only ever **read** through Supabase (Realtime notifications). Row-level security limits each person to their
  own requests, invitations, sessions they're in, their private notes, etc. `anon` can read only the topic list.
  `authenticated` has no insert/update/delete grants at all.
- All writes go through Next.js server actions → `src/lib/server/service.ts`, which resolves the user with
  `supabase.auth.getUser()` (verified with the Auth server), re-reads their role/status from the database, and checks
  every rule. The database adds transition triggers, unique indexes (one pending invitation per request, one session per
  request), CHECK constraints, rate-limit triggers, and an append-only audit log.

## 2. LiveKit (optional voice/video)

1. Create a project on LiveKit Cloud (or run `livekit-server --dev` locally).
2. Set `LIVEKIT_URL` (wss://…), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
3. Nothing else is needed: rooms are created on first join. No egress (recording) is configured, and none should be.

Tokens come from `POST /api/sessions/:id/token`. The server checks that the caller is a participant of an **active**,
**unblocked** session whose format isn't text, then issues a 10-minute token for that session's random room name,
identity = user id. Camera publishing is in the grant only after both people opted in to video; otherwise only the
microphone may publish. Guessing a room name gives nothing without a token.

## 3. Optional AI-assisted categorization

Set `ANTHROPIC_API_KEY` to have topic suggestions come from Claude (structured output constrained to the topic list).
On any error, timeout or refusal the deterministic keyword tagger is used. Emergency and high-stakes screening always
runs the deterministic rules as well. People always confirm or correct the topic. `PEOPLE_AI=off` disables it.

## 4. Running tests locally

```bash
npm test                               # unit + service suite (memory)
createdb people_test                   # disposable database; tests drop and recreate its public schema
npm run test:db                        # same suite on Postgres + RLS/trigger checks
npm run build && npm run e2e           # Playwright, demo mode, desktop + phone
npm run check:secrets
```
`npm run test:db` uses `postgres://postgres:postgres@localhost:5432/people_test`; override with `DATABASE_URL_TEST`.

## 5. Deploying

Any Node host that supports Next.js 16 works. Demo mode keeps state in one process's memory, so run a single instance
for demos. Live mode is stateless apart from Postgres; Supabase Realtime handles fan-out.
