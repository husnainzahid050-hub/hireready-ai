-- Security: per-session quotas on expensive (LLM-consuming) actions.
--
-- Why: without a cap, one guest token can loop "re-upload CV -> analyze" forever, and every
-- loop spends ~4 LLM calls plus embeddings on our free-tier keys (cost / quota exhaustion).
-- Rate limiting per IP (Upstash, Phase 7) complements this; this cap needs no extra account.
--
-- consume_quota() is atomic: one INSERT .. ON CONFLICT DO UPDATE .. WHERE count < limit.
-- Two concurrent requests can never both take the last unit.

create table public.session_usage (
  session_id uuid not null references public.sessions (id) on delete cascade,
  action     text not null check (char_length(action) between 1 and 64),
  count      int  not null default 0 check (count >= 0),
  updated_at timestamptz not null default now(),
  primary key (session_id, action)
);

alter table public.session_usage enable row level security;
revoke all on public.session_usage from anon, authenticated;

-- Returns true and increments the counter if the session still has budget for `p_action`;
-- returns false (and changes nothing) once `p_limit` is reached.
create or replace function public.consume_quota(
  p_session_id uuid,
  p_action     text,
  p_limit      int
)
returns boolean
language plpgsql
volatile
security invoker
set search_path = public, pg_temp
as $$
declare
  new_count int;
begin
  if p_limit is null or p_limit <= 0 then
    return false;
  end if;
  insert into public.session_usage as u (session_id, action, count)
  values (p_session_id, p_action, 1)
  on conflict (session_id, action) do update
    set count = u.count + 1, updated_at = now()
    where u.count < p_limit
  returning u.count into new_count;
  return new_count is not null;
end;
$$;

revoke execute on function public.consume_quota(uuid, text, int) from public, anon, authenticated;
grant execute on function public.consume_quota(uuid, text, int) to service_role;
