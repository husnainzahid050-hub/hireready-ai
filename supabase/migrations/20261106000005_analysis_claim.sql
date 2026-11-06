-- Analysis claim: at most ONE gap-analysis run per session at a time (QA bug B3).
--
-- Why: two analyze requests for the same session (a second tab, a double click, a retry while
-- the first run is still going) each ran the full LLM pipeline. That doubled token spend
-- (triggering Groq 429s) and the later run overwrote the first, so a reload could show
-- different results.
--
-- claim_analysis() is one conditional UPDATE on the session row, so it is atomic: Postgres
-- locks the row, and a concurrent second UPDATE re-checks the WHERE clause after the first
-- commits and then matches nothing. A claim older than p_stale_seconds is treated as abandoned
-- (the serverless function was killed or crashed), so a session can never be stuck forever.
-- The backend clears the claim (analysis_started_at = null) when its run ends.

alter table public.sessions add column analysis_started_at timestamptz null;

-- Returns true if the caller now owns the run; false if another run is in progress or the
-- session already has a saved analysis.
create or replace function public.claim_analysis(
  p_session_id    uuid,
  p_stale_seconds int
)
returns boolean
language sql
volatile
security invoker
set search_path = public, pg_temp
as $$
  with claimed as (
    update public.sessions s
       set analysis_started_at = now()
     where s.id = p_session_id
       and (s.analysis_started_at is null
            or s.analysis_started_at < now() - make_interval(secs => greatest(p_stale_seconds, 1)))
       and not exists (select 1 from public.gap_analyses g where g.session_id = p_session_id)
    returning s.id
  )
  select exists (select 1 from claimed);
$$;

revoke execute on function public.claim_analysis(uuid, int) from public, anon, authenticated;
grant execute on function public.claim_analysis(uuid, int) to service_role;
