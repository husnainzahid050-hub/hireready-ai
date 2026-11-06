-- hybrid_search: vector similarity + full-text rank, fused with Reciprocal Rank Fusion (RRF).
--
-- RRF score for a row = sum over rankers of  weight / (rrf_k + rank_in_that_ranker)
-- A row ranked #1 by both rankers beats a row ranked #1 by only one.
-- Rows missing from a ranker simply contribute 0 for it.
--
-- filter (jsonb):
--   {"source": "knowledge", "competency": "python", "level": "junior"}   (rubric KB)
--   {"source": "cv", "session_id": "<uuid>"}                             (one session's CV)
-- Based on the pattern in https://supabase.com/docs/guides/ai/hybrid-search

create or replace function public.hybrid_search(
  query_embedding  extensions.vector(768),
  query_text       text,
  match_count      int default 5,
  filter           jsonb default '{}'::jsonb,
  full_text_weight double precision default 1.0,
  semantic_weight  double precision default 1.0,
  rrf_k            int default 50
)
returns table (
  id          uuid,
  content     text,
  metadata    jsonb,
  competency  text,
  level       text,
  source_file text,
  document_id uuid,
  score       double precision
)
language plpgsql
stable
security invoker
set search_path = public, extensions, pg_temp
as $$
#variable_conflict use_column
declare
  k          int := least(greatest(coalesce(match_count, 5), 1), 50);
  pool       int := least(greatest(coalesce(match_count, 5), 1), 50) * 4;
  src        text := coalesce(filter ->> 'source', 'knowledge');
  f_comp     text := filter ->> 'competency';
  f_level    text := filter ->> 'level';
  f_session  uuid := nullif(filter ->> 'session_id', '')::uuid;
  tsq        tsquery := websearch_to_tsquery('english', coalesce(query_text, ''));
begin
  if src = 'knowledge' then
    return query
    with candidates as (
      select c.* from public.knowledge_chunks c
      where (f_comp is null or c.competency = f_comp)
        and (f_level is null or c.level = 'all' or c.level = f_level)
    ),
    fts as (
      select c.id, row_number() over (order by ts_rank_cd(c.tsv, tsq) desc) as r
      from candidates c
      where c.tsv @@ tsq
      order by r
      limit pool
    ),
    sem as (
      select c.id, row_number() over (order by c.embedding <=> query_embedding) as r
      from candidates c
      order by r
      limit pool
    )
    select c.id, c.content, c.metadata, c.competency, c.level, c.source_file,
           null::uuid,
           (coalesce(full_text_weight / (rrf_k + fts.r), 0.0)
            + coalesce(semantic_weight / (rrf_k + sem.r), 0.0))::double precision
    from fts
    full outer join sem on fts.id = sem.id
    join public.knowledge_chunks c on c.id = coalesce(fts.id, sem.id)
    order by 8 desc
    limit k;

  elsif src = 'cv' then
    if f_session is null then
      raise exception 'hybrid_search: filter.session_id is required for source=cv';
    end if;
    return query
    with candidates as (
      select c.* from public.doc_chunks c
      join public.documents d on d.id = c.document_id
      where d.session_id = f_session and d.kind = 'cv'
    ),
    fts as (
      select c.id, row_number() over (order by ts_rank_cd(c.tsv, tsq) desc) as r
      from candidates c
      where c.tsv @@ tsq
      order by r
      limit pool
    ),
    sem as (
      select c.id, row_number() over (order by c.embedding <=> query_embedding) as r
      from candidates c
      order by r
      limit pool
    )
    select c.id, c.content, c.metadata, null::text, null::text, null::text,
           c.document_id,
           (coalesce(full_text_weight / (rrf_k + fts.r), 0.0)
            + coalesce(semantic_weight / (rrf_k + sem.r), 0.0))::double precision
    from fts
    full outer join sem on fts.id = sem.id
    join public.doc_chunks c on c.id = coalesce(fts.id, sem.id)
    order by 8 desc
    limit k;

  else
    raise exception 'hybrid_search: unknown source %', src;
  end if;
end;
$$;

-- Only the backend (service role) may call it.
revoke execute on function public.hybrid_search(
  extensions.vector, text, int, jsonb, double precision, double precision, int
) from public, anon, authenticated;
grant execute on function public.hybrid_search(
  extensions.vector, text, int, jsonb, double precision, double precision, int
) to service_role;
