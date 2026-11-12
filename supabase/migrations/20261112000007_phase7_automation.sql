-- Phase 7: reminders with their own lifetime, cron bookkeeping, batched cleanup, demo cache.
--
-- 1. sessions.reminders_opt_in: the "Send me 7 daily prep emails" checkbox, separate from the
--    "Email me my report" consent (email_opt_in). Two purposes, two unticked boxes.
-- 2. reminders (replaces the never-used Phase 1 placeholder): a SMALL record that outlives the
--    session. The 7-day plan starts after the interview, so it runs past the 7-day guest expiry;
--    the cleanup job detaches the row from its session instead of deleting it. It holds only the
--    email, job title, the plan days and a hashed single-purpose token, and has its own expiry.
--    "Delete my data" still removes it (ON DELETE CASCADE); only the cleanup job detaches first.
-- 3. cron_runs: one row per cron run (proof the cleanup ran, shown on the Engineering page).
-- 4. cleanup_expired(p_batch): deletes expired sessions in batches (all children cascade),
--    detaches their reminders, deletes expired reminders and old cron_runs, returns counts.
-- 5. copy_demo_analysis(p_session_id): a demo session reuses the analysis (profiles, CV chunks
--    with embeddings, gap analysis) of an earlier demo session with the same CV + JD text,
--    so the most-clicked path costs no LLM or embedding calls.

alter table public.sessions add column if not exists reminders_opt_in boolean not null default false;

-- The Phase 1 placeholder had a 1:1 cascade to sessions, so the cleanup job would have deleted
-- an active plan on day 7. Nothing ever wrote to it.
drop table if exists public.reminders;

create table public.reminders (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid null references public.sessions (id) on delete cascade,
  email          text not null check (char_length(email) between 3 and 320),
  email_hash     text not null check (char_length(email_hash) = 64),
  role_title     text not null default '' check (char_length(role_title) <= 200),
  plan           jsonb not null check (jsonb_typeof(plan) = 'array'),
  -- token = HMAC(REMINDER_TOKEN_SECRET, token_nonce); only its SHA-256 is stored, so a database
  -- leak alone can't unsubscribe or confirm anyone.
  token_nonce    text not null check (char_length(token_nonce) between 16 and 64),
  token_hash     text not null unique check (char_length(token_hash) = 64),
  status         text not null default 'pending'
                 check (status in ('pending', 'active', 'paused', 'finished')),
  day_index      int not null default 0 check (day_index between 0 and 7),   -- last day sent
  last_click_day int not null default 0 check (last_click_day between 0 and 7),
  next_send_date date null,
  confirmed_at   timestamptz null,
  last_sent_at   timestamptz null,
  created_at     timestamptz not null default now(),
  -- pending: 3 days to confirm; afterwards pushed to "last send + 3 days" on every send.
  expires_at     timestamptz not null default (now() + interval '3 days')
);
create unique index reminders_session_idx on public.reminders (session_id) where session_id is not null;
create index reminders_due_idx on public.reminders (next_send_date) where status = 'active';
create index reminders_expires_idx on public.reminders (expires_at);

create table public.cron_runs (
  id     bigint generated always as identity primary key,
  name   text not null check (char_length(name) between 1 and 64),
  ran_at timestamptz not null default now(),
  stats  jsonb not null default '{}'::jsonb
);
create index cron_runs_name_idx on public.cron_runs (name, ran_at desc);

alter table public.reminders enable row level security;
alter table public.cron_runs enable row level security;
revoke all on public.reminders, public.cron_runs from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

-- ---------------------------------------------------------------------------
-- cleanup_expired: idempotent, batched, safe to re-run (Vercel cron may retry).
-- ---------------------------------------------------------------------------
create or replace function public.cleanup_expired(p_batch int default 200)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = public, pg_temp
as $$
declare
  ids        uuid[];
  stats      jsonb;
  n_rem      int;
  n_runs     int;
begin
  select coalesce(array_agg(s.id), '{}') into ids
    from (select id from public.sessions
           where expires_at < now()
           order by expires_at
           limit least(greatest(coalesce(p_batch, 200), 1), 1000)
           for update skip locked) s;

  -- Keep running prep plans alive: detach them before the cascade would delete them.
  update public.reminders set session_id = null where session_id = any(ids);

  stats := jsonb_build_object(
    'sessions',        cardinality(ids),
    'documents',       (select count(*) from public.documents where session_id = any(ids)),
    'doc_chunks',      (select count(*) from public.doc_chunks c
                          join public.documents d on d.id = c.document_id
                         where d.session_id = any(ids)),
    'gap_analyses',    (select count(*) from public.gap_analyses where session_id = any(ids)),
    'questions',       (select count(*) from public.questions where session_id = any(ids)),
    'answers',         (select count(*) from public.answers a
                          join public.questions q on q.id = a.question_id
                         where q.session_id = any(ids)),
    'interview_state', (select count(*) from public.interview_state where session_id = any(ids)),
    'reports',         (select count(*) from public.reports where session_id = any(ids)),
    'session_usage',   (select count(*) from public.session_usage where session_id = any(ids))
  );

  delete from public.sessions where id = any(ids);  -- every child table cascades

  with gone as (delete from public.reminders where expires_at < now() returning 1)
  select count(*) into n_rem from gone;
  with gone as (delete from public.cron_runs where ran_at < now() - interval '30 days' returning 1)
  select count(*) into n_runs from gone;

  stats := stats || jsonb_build_object(
    'reminders', n_rem,
    'cron_runs', n_runs,
    'more', exists (select 1 from public.sessions where expires_at < now())
  );
  insert into public.cron_runs (name, stats) values ('cleanup', stats);
  return stats;
end;
$$;

-- ---------------------------------------------------------------------------
-- copy_demo_analysis: true if this demo session now has a copied analysis.
-- ---------------------------------------------------------------------------
create or replace function public.copy_demo_analysis(p_session_id uuid)
returns boolean
language plpgsql
volatile
security invoker
set search_path = public, pg_temp
as $$
declare
  src     uuid;
  src_cv  uuid;
  dst_cv  uuid;
begin
  -- Serialize concurrent calls for the same session (double click, second tab).
  perform 1 from public.sessions where id = p_session_id and is_demo for update;
  if not found then
    return false;
  end if;
  if exists (select 1 from public.gap_analyses where session_id = p_session_id) then
    return false;
  end if;

  select s.id into src
    from public.sessions s
    join public.gap_analyses g on g.session_id = s.id
    join public.documents scv on scv.session_id = s.id and scv.kind = 'cv'
    join public.documents sjd on sjd.session_id = s.id and sjd.kind = 'jd'
    join public.documents mcv on mcv.session_id = p_session_id and mcv.kind = 'cv'
                              and mcv.content_hash = scv.content_hash
    join public.documents mjd on mjd.session_id = p_session_id and mjd.kind = 'jd'
                              and mjd.content_hash = sjd.content_hash
   where s.is_demo
     and s.id <> p_session_id
     and s.expires_at > now()
     and scv.structured is not null
     and sjd.structured is not null
   order by g.created_at desc
   limit 1;
  if src is null then
    return false;
  end if;

  update public.documents d
     set structured = s.structured
    from public.documents s
   where s.session_id = src and d.session_id = p_session_id and d.kind = s.kind;

  select id into src_cv from public.documents where session_id = src and kind = 'cv';
  select id into dst_cv from public.documents where session_id = p_session_id and kind = 'cv';
  delete from public.doc_chunks where document_id = dst_cv;
  insert into public.doc_chunks (document_id, chunk_index, content, embedding, metadata)
  select dst_cv, chunk_index, content, embedding, metadata
    from public.doc_chunks where document_id = src_cv;

  insert into public.gap_analyses
         (session_id, match_score, breakdown, gaps, strengths, likely_questions, prep_plan)
  select p_session_id, match_score, breakdown, gaps, strengths, likely_questions, prep_plan
    from public.gap_analyses where session_id = src
  on conflict (session_id) do nothing;

  update public.sessions
     set status = 'analyzed',
         role_title = (select role_title from public.sessions where id = src)
   where id = p_session_id;
  return true;
end;
$$;

revoke execute on function public.cleanup_expired(int) from public, anon, authenticated;
grant execute on function public.cleanup_expired(int) to service_role;
revoke execute on function public.copy_demo_analysis(uuid) from public, anon, authenticated;
grant execute on function public.copy_demo_analysis(uuid) to service_role;
