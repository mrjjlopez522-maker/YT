-- People — core schema.
-- Conventions: snake_case columns mirror src/lib/server/schema.ts. Status columns
-- are text + CHECK so new states can be added with a migration.

create extension if not exists pgcrypto;

-- ───────────── taxonomy ─────────────
create table public.topics (
  id text primary key,
  parent_id text references public.topics(id),
  name text not null,
  description text,
  sensitivity text not null default 'standard' check (sensitivity in ('standard', 'perspective', 'high_stakes')),
  keywords text[] not null default '{}'
);

-- ───────────── people ─────────────
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(display_name) between 1 and 40),
  avatar_color text not null default '#4f46e5',
  intro text not null default '' check (char_length(intro) <= 400),
  can_help_with text not null default '' check (char_length(can_help_with) <= 400),
  curious_about text not null default '' check (char_length(curious_about) <= 400),
  languages text[] not null default '{}' check (cardinality(languages) between 1 and 8),
  formats text[] not null default '{text}' check (formats <@ array['text', 'voice', 'video'] and cardinality(formats) >= 1),
  timezone text not null default 'UTC',
  location_broad text not null default '' check (char_length(location_broad) <= 60),
  interests text[] not null default '{}',
  cannot_advise text not null default '' check (char_length(cannot_advise) <= 400),
  session_length_minutes int not null default 30 check (session_length_minutes between 10 and 120),
  available_until timestamptz,
  role text not null default 'member' check (role in ('member', 'moderator')),
  status text not null default 'active' check (status in ('active', 'suspended')),
  -- Self-declared. Not robust age assurance; see docs/TRUST_AND_SAFETY.md.
  adult_confirmed boolean not null default false,
  onboarded boolean not null default false,
  created_at timestamptz not null default now(),
  check (not onboarded or adult_confirmed)
);

create table public.helper_topics (
  helper_id uuid not null references public.profiles(id) on delete cascade,
  topic_id text not null references public.topics(id),
  kind text not null check (kind in ('lived', 'professional')), -- self-described
  detail text not null default '' check (char_length(detail) <= 300),
  welcomes_beginners boolean not null default true,
  primary key (helper_id, topic_id)
);

create table public.availability_windows (
  id uuid primary key default gen_random_uuid(),
  helper_id uuid not null references public.profiles(id) on delete cascade,
  weekday int not null check (weekday between 0 and 6),
  start_minute int not null check (start_minute between 0 and 1439),
  end_minute int not null check (end_minute between 1 and 1440),
  check (start_minute < end_minute)
);
create index on public.availability_windows (helper_id);

-- Credentials actually reviewed by the platform. Applies to ONE topic.
create table public.credential_reviews (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  topic_id text not null references public.topics(id),
  title text not null check (char_length(title) between 1 and 120),
  issuer text not null default '',
  evidence_note text not null default '',
  status text not null default 'pending' check (status in ('pending', 'verified', 'rejected', 'revoked')),
  reviewed_by uuid references public.profiles(id),
  reviewed_at timestamptz,
  reviewer_note text not null default '',
  created_at timestamptz not null default now(),
  check (reviewed_by is null or reviewed_by <> user_id),
  check (status = 'pending' or reviewed_by is not null)
);
create index on public.credential_reviews (user_id);
create index on public.credential_reviews (status);

-- ───────────── requests & matching ─────────────
create table public.requests (
  id uuid primary key default gen_random_uuid(),
  requester_id uuid not null references public.profiles(id) on delete cascade,
  question text not null check (char_length(question) between 5 and 600),
  intent text not null check (intent in ('ask', 'learn', 'move', 'explore')),
  topic_id text not null references public.topics(id),
  tags text[] not null default '{}',
  language text not null,
  formats text[] not null check (formats <@ array['text', 'voice', 'video'] and cardinality(formats) >= 1),
  timing text not null check (timing in ('now', 'later')),
  preferred_time timestamptz,
  experience_level text not null default '' check (experience_level in ('', 'new', 'some', 'experienced')),
  context text not null default '' check (char_length(context) <= 800),
  clarification_question text not null default '',
  clarification_answer text not null default '',
  broadened text[] not null default '{}' check (broadened <@ array['formats', 'topic']),
  status text not null default 'open'
    check (status in ('open', 'waiting', 'matched', 'async_open', 'answered', 'closed', 'cancelled')),
  auto_match boolean not null default false,
  follow_up_of uuid,
  created_at timestamptz not null default now(),
  check (timing = 'now' or preferred_time is not null)
);
create index on public.requests (requester_id, created_at desc);
create index on public.requests (status) where status in ('async_open', 'answered');

create table public.invitations (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.requests(id) on delete cascade,
  requester_id uuid not null references public.profiles(id) on delete cascade,
  helper_id uuid not null references public.profiles(id) on delete cascade,
  status text not null default 'pending'
    check (status in ('pending', 'accepted', 'declined', 'expired', 'cancelled', 'unavailable')),
  auto boolean not null default false,
  proposed_time timestamptz,
  expires_at timestamptz not null,
  responded_at timestamptz,
  created_at timestamptz not null default now(),
  check (requester_id <> helper_id)
);
-- One outstanding invitation per request: the core guard against duplicate matches.
create unique index invitations_one_pending_per_request on public.invitations (request_id) where status = 'pending';
-- A helper is never invited twice for the same request.
create unique index invitations_once_per_helper on public.invitations (request_id, helper_id);
create index on public.invitations (helper_id, status);
create index on public.invitations (requester_id, created_at desc);
create index on public.invitations (expires_at) where status = 'pending';

create table public.async_responses (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.requests(id) on delete cascade,
  helper_id uuid not null references public.profiles(id) on delete cascade,
  body text not null check (char_length(body) between 2 and 3000),
  created_at timestamptz not null default now()
);
create index on public.async_responses (request_id);
create index on public.async_responses (helper_id, created_at desc);

-- ───────────── sessions ─────────────
create table public.sessions (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null unique references public.requests(id) on delete cascade, -- one session per request
  status text not null check (status in ('scheduled', 'active', 'ended', 'cancelled')),
  goal text not null default '' check (char_length(goal) <= 600),
  format text not null check (format in ('text', 'voice', 'video')),
  scheduled_at timestamptz,
  started_at timestamptz,
  ended_at timestamptz,
  room_name text not null unique, -- random; a token is still required to join
  created_at timestamptz not null default now(),
  timer_ends_at timestamptz,
  timer_label text not null default ''
);
alter table public.requests
  add constraint requests_follow_up_fk foreign key (follow_up_of) references public.sessions(id) on delete set null;

create table public.session_participants (
  session_id uuid not null references public.sessions(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role text not null check (role in ('requester', 'helper')),
  video_opt_in boolean not null default false, -- camera is off until BOTH opt in
  keep_going boolean not null default false,
  reconnect_opt_in boolean not null default false,
  addressed text not null default '' check (addressed in ('', 'yes', 'partly', 'no')),
  left_at timestamptz,
  primary key (session_id, user_id)
);
create index on public.session_participants (user_id);
create unique index session_one_role_each on public.session_participants (session_id, role);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions(id) on delete cascade,
  sender_id uuid references public.profiles(id) on delete set null, -- null = system notice
  body text not null check (char_length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index on public.messages (session_id, created_at);
create index on public.messages (sender_id, created_at desc);

create table public.checklist_items (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions(id) on delete cascade,
  text text not null check (char_length(text) between 1 and 200),
  done boolean not null default false,
  created_by uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  kind text not null default 'task' check (kind in ('step', 'try', 'task'))
);
create index on public.checklist_items (session_id);

-- Shared between the two participants.
create table public.shared_notes (
  session_id uuid primary key references public.sessions(id) on delete cascade,
  body text not null default '' check (char_length(body) <= 8000),
  updated_by uuid references public.profiles(id) on delete set null,
  updated_at timestamptz not null default now()
);

-- Visible only to their author. Kept in a separate table from shared notes on purpose.
create table public.private_notes (
  session_id uuid not null references public.sessions(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  body text not null default '' check (char_length(body) <= 8000),
  updated_at timestamptz not null default now(),
  primary key (session_id, user_id)
);

create table public.takeaways (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  session_id uuid references public.sessions(id) on delete set null,
  title text not null check (char_length(title) between 1 and 120),
  body text not null default '',
  next_steps text not null default '',
  created_at timestamptz not null default now()
);
create index on public.takeaways (user_id, created_at desc);

create table public.feedback (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions(id) on delete cascade,
  from_user uuid not null references public.profiles(id) on delete cascade,
  to_user uuid not null references public.profiles(id) on delete cascade,
  helpful int not null check (helpful between 1 and 5),
  respectful boolean not null default true,
  comment text not null default '' check (char_length(comment) <= 1000), -- private
  created_at timestamptz not null default now(),
  unique (session_id, from_user),
  check (from_user <> to_user)
);
create index on public.feedback (to_user);

-- ───────────── safety ─────────────
create table public.blocks (
  blocker_id uuid not null references public.profiles(id) on delete cascade,
  blocked_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker_id, blocked_id),
  check (blocker_id <> blocked_id)
);
create index on public.blocks (blocked_id);

-- Restricted data: visible to the reporter (their own) and moderators only.
create table public.reports (
  id uuid primary key default gen_random_uuid(),
  reporter_id uuid not null references public.profiles(id) on delete cascade,
  reported_user_id uuid not null references public.profiles(id) on delete cascade,
  session_id uuid references public.sessions(id) on delete set null,
  reason text not null check (reason in ('harassment', 'inappropriate_media', 'spam', 'unsafe_advice', 'impersonation', 'other')),
  details text not null default '' check (char_length(details) <= 2000),
  status text not null default 'open' check (status in ('open', 'actioned', 'dismissed')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  check (reporter_id <> reported_user_id)
);
create index on public.reports (status, created_at desc);
create index on public.reports (reporter_id, created_at desc);
create index on public.reports (reported_user_id);

-- Append-only audit trail (see triggers in 0002).
create table public.moderation_actions (
  id uuid primary key default gen_random_uuid(),
  moderator_id uuid not null references public.profiles(id),
  action text not null check (action in (
    'suspend', 'unsuspend', 'report_actioned', 'report_dismissed',
    'credential_verified', 'credential_rejected', 'credential_revoked', 'evidence_viewed')),
  target_user_id uuid references public.profiles(id) on delete set null,
  report_id uuid references public.reports(id) on delete set null,
  credential_id uuid references public.credential_reviews(id) on delete set null,
  reason text not null default '',
  created_at timestamptz not null default now()
);
create index on public.moderation_actions (created_at desc);
