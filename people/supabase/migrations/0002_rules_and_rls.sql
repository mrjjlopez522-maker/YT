-- People — state machines, integrity rules and row-level security.
--
-- Write model: browsers never write tables directly. All writes go through the
-- Next.js server (service.ts), which connects with a server-only DATABASE_URL.
-- The anon/authenticated roles get SELECT policies only, scoped to the signed-in
-- user, so Supabase Realtime and the public REST API can never expose another
-- person's requests, sessions, messages or notes.

-- ───────────── state machines (mirror src/lib/domain/states.ts) ─────────────
create or replace function public.enforce_transition() returns trigger
language plpgsql as $$
declare
  allowed text[];
begin
  if new.status = old.status then
    return new;
  end if;
  allowed := case tg_table_name
    when 'requests' then case old.status
      when 'open' then array['waiting', 'async_open', 'cancelled']
      when 'waiting' then array['open', 'matched', 'cancelled']
      when 'matched' then array['closed', 'open']
      when 'async_open' then array['answered', 'waiting', 'open', 'cancelled']
      when 'answered' then array['closed', 'waiting', 'open']
      else array[]::text[] end
    when 'invitations' then case old.status
      when 'pending' then array['accepted', 'declined', 'expired', 'cancelled', 'unavailable']
      else array[]::text[] end
    when 'sessions' then case old.status
      when 'scheduled' then array['active', 'cancelled']
      when 'active' then array['ended']
      else array[]::text[] end
    when 'credential_reviews' then case old.status
      when 'pending' then array['verified', 'rejected']
      when 'verified' then array['revoked']
      else array[]::text[] end
    when 'reports' then case old.status
      when 'open' then array['actioned', 'dismissed']
      else array[]::text[] end
  end;
  if not (new.status = any (allowed)) then
    raise exception 'invalid % transition: % -> %', tg_table_name, old.status, new.status
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

create trigger requests_transition before update of status on public.requests
  for each row execute function public.enforce_transition();
create trigger invitations_transition before update of status on public.invitations
  for each row execute function public.enforce_transition();
create trigger sessions_transition before update of status on public.sessions
  for each row execute function public.enforce_transition();
create trigger credentials_transition before update of status on public.credential_reviews
  for each row execute function public.enforce_transition();
create trigger reports_transition before update of status on public.reports
  for each row execute function public.enforce_transition();

-- An accepted invitation can't be accepted past its deadline.
create or replace function public.invitation_deadline() returns trigger
language plpgsql as $$
begin
  if new.status = 'accepted' and old.status = 'pending' and old.expires_at <= now() then
    raise exception 'invitation expired' using errcode = 'check_violation';
  end if;
  return new;
end $$;
create trigger invitations_deadline before update of status on public.invitations
  for each row execute function public.invitation_deadline();

-- Audit trail is append-only, for every role.
create or replace function public.forbid_change() returns trigger
language plpgsql as $$
begin
  raise exception '% is append-only', tg_table_name using errcode = 'insufficient_privilege';
end $$;
create trigger moderation_actions_append_only before update or delete on public.moderation_actions
  for each row execute function public.forbid_change();

-- Database-level rate limits: a backstop behind the service's own checks.
create or replace function public.rate_limit() returns trigger
language plpgsql as $$
declare
  n int;
begin
  if tg_table_name = 'requests' then
    select count(*) into n from public.requests where requester_id = new.requester_id and created_at > now() - interval '1 hour';
    if n >= 20 then raise exception 'rate limit: requests' using errcode = 'P0429'; end if;
  elsif tg_table_name = 'invitations' then
    select count(*) into n from public.invitations where requester_id = new.requester_id and created_at > now() - interval '1 hour';
    if n >= 40 then raise exception 'rate limit: invitations' using errcode = 'P0429'; end if;
  elsif tg_table_name = 'messages' and new.sender_id is not null then
    select count(*) into n from public.messages where sender_id = new.sender_id and created_at > now() - interval '1 minute';
    if n >= 60 then raise exception 'rate limit: messages' using errcode = 'P0429'; end if;
  end if;
  return new;
end $$;
create trigger requests_rate before insert on public.requests for each row execute function public.rate_limit();
create trigger invitations_rate before insert on public.invitations for each row execute function public.rate_limit();
create trigger messages_rate before insert on public.messages for each row execute function public.rate_limit();

-- ───────────── helpers for policies ─────────────
-- SECURITY DEFINER so policies can consult other tables without recursive RLS.
create or replace function public.is_moderator() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'moderator' and status = 'active');
$$;

create or replace function public.is_session_member(sid uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.session_participants sp
    join public.profiles p on p.id = sp.user_id and p.status = 'active'
    where sp.session_id = sid and sp.user_id = auth.uid()
  );
$$;

revoke all on function public.is_moderator() from public;
revoke all on function public.is_session_member(uuid) from public;
grant execute on function public.is_moderator() to authenticated;
grant execute on function public.is_session_member(uuid) to authenticated;

-- ───────────── row-level security ─────────────
alter table public.topics enable row level security;
alter table public.profiles enable row level security;
alter table public.helper_topics enable row level security;
alter table public.availability_windows enable row level security;
alter table public.credential_reviews enable row level security;
alter table public.requests enable row level security;
alter table public.invitations enable row level security;
alter table public.async_responses enable row level security;
alter table public.sessions enable row level security;
alter table public.session_participants enable row level security;
alter table public.messages enable row level security;
alter table public.checklist_items enable row level security;
alter table public.shared_notes enable row level security;
alter table public.private_notes enable row level security;
alter table public.takeaways enable row level security;
alter table public.feedback enable row level security;
alter table public.blocks enable row level security;
alter table public.reports enable row level security;
alter table public.moderation_actions enable row level security;

-- No anonymous access to anything except the public topic list.
revoke all on all tables in schema public from anon;
revoke insert, update, delete, truncate on all tables in schema public from authenticated;
grant select on all tables in schema public to authenticated;
grant select on public.topics to anon;

create policy topics_read on public.topics for select using (true);

create policy profiles_self on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_moderator());

create policy helper_topics_self on public.helper_topics for select to authenticated
  using (helper_id = auth.uid());
create policy windows_self on public.availability_windows for select to authenticated
  using (helper_id = auth.uid());

create policy credentials_owner_or_mod on public.credential_reviews for select to authenticated
  using (user_id = auth.uid() or public.is_moderator());

create policy requests_owner on public.requests for select to authenticated
  using (requester_id = auth.uid());

create policy invitations_parties on public.invitations for select to authenticated
  using (requester_id = auth.uid() or helper_id = auth.uid());

create policy async_responses_parties on public.async_responses for select to authenticated
  using (helper_id = auth.uid()
    or exists (select 1 from public.requests r where r.id = request_id and r.requester_id = auth.uid()));

create policy sessions_members on public.sessions for select to authenticated
  using (public.is_session_member(id));
create policy participants_members on public.session_participants for select to authenticated
  using (public.is_session_member(session_id));
create policy messages_members on public.messages for select to authenticated
  using (public.is_session_member(session_id));
create policy checklist_members on public.checklist_items for select to authenticated
  using (public.is_session_member(session_id));
create policy shared_notes_members on public.shared_notes for select to authenticated
  using (public.is_session_member(session_id));

create policy private_notes_author on public.private_notes for select to authenticated
  using (user_id = auth.uid());
create policy takeaways_owner on public.takeaways for select to authenticated
  using (user_id = auth.uid());
create policy feedback_author on public.feedback for select to authenticated
  using (from_user = auth.uid());
create policy blocks_blocker on public.blocks for select to authenticated
  using (blocker_id = auth.uid());

-- Report evidence is restricted: reporters see their own report; moderators see all.
create policy reports_reporter_or_mod on public.reports for select to authenticated
  using (reporter_id = auth.uid() or public.is_moderator());
create policy moderation_actions_mod on public.moderation_actions for select to authenticated
  using (public.is_moderator());

-- ───────────── realtime ─────────────
-- Change notifications for the session room and inboxes. Delivery respects the
-- SELECT policies above.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table
      public.messages, public.checklist_items, public.shared_notes, public.sessions,
      public.session_participants, public.invitations, public.requests;
  end if;
end $$;
