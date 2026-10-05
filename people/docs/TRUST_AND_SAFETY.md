# Trust and safety

## Implemented

- **Adults, invited.** Onboarding requires confirming 18+. This is a self-declaration and **not robust age assurance**.
  The real control for the pilot is invite-only sign-up (`PEOPLE_INVITE_ONLY=true` + Supabase invites).
- **Consent to talk.** Sessions start only when the helper accepts the requester's invitation. Declining needs no reason.
  Invitations expire; helpers' "available now" switches off on its own.
- **Private by default.** Requests, invitations, sessions, messages and notes are visible only to the people involved
  (service checks + RLS). Non-participants get the same "not found" as for a non-existent session. Pages send
  `X-Robots-Tag: noindex` and `robots: noindex`.
- **Calls.** Tokens are issued server-side only to verified participants of active, unblocked sessions, last 10 minutes,
  and are bound to a random room name. Camera publishing requires mutual opt-in and is enforced in the token grant.
  Everyone can mute, stop receiving the other person's audio/video immediately, and leave. Nothing is recorded or
  transcribed, and no summaries are generated from audio or video.
- **Blocking** ends shared active/upcoming sessions immediately, withdraws pending invitations, hides each person from the
  other's matches and profile view, and stops messages and call tokens.
- **Reports** go to moderators only. Opening a report's session messages is recorded as `evidence_viewed` in the audit log.
  Moderators can resolve reports, suspend/reinstate (which withdraws invitations and ends sessions), and review
  credentials. They cannot act on reports about themselves or review their own credentials or change their own status.
  The audit log is append-only at the database level.
- **Credentials** are reviewed per topic; users can't create a verified badge. Experience is labelled "lived" or
  "professional (self-described)".
- **High-stakes and emergencies.** Emergency phrases block the request and show emergency guidance. Medical, legal and
  personal-investment topics are recognised and not matched; nobody is presented as a qualified professional.
- **Respectful perspectives.** Religion and culture topics show a note that people share their own perspective, not
  official teaching, and that declining a subject is fine.
- **Rate limits** on requests, invitations, messages, reports, written answers and AI categorization (service), with a
  higher database backstop.

## Not implemented (do not claim otherwise)

- No automated media moderation. LiveKit transports media; it doesn't detect nudity, violence or abuse. Accepting video
  does not make a call safe.
- No automated text moderation or spam detection.
- No robust age or identity verification; no automated credential verification.
- No IP/device-level abuse controls or CAPTCHA.
- No notification to moderators when a report arrives (they check the dashboard).
- No data-export or account-deletion flow in the UI (deleting a member's auth user cascades in the database).

## Integration boundary for future media moderation

All call access goes through `Service.callToken` → `livekitMinter` (`src/lib/server/livekit.ts`). A future moderation
service can be added there (e.g. LiveKit egress to a moderation provider, only with an explicit, recorded consent flow),
and enforcement can use the existing `setSuspended`/`closeSession` paths, which already end sessions and stop new tokens.

## Restricted data

Report details, report evidence (session messages) and private notes are restricted. Moderators have no RLS read access
to messages; they can only see evidence through the audited server path.
