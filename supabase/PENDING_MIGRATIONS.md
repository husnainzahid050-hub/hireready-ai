# Pending migrations (apply before deploying the current backend)

The live Supabase project has `20261106000001_init_schema.sql` and
`20261106000002_hybrid_search.sql`. Paste these files into the Supabase **SQL editor** and run
them **in this order**, one at a time:

| # | File | What it adds | Without it |
|---|---|---|---|
| 1 | [`migrations/20261106000004_security.sql`](migrations/20261106000004_security.sql) | `session_usage` table + `consume_quota()` (per-session quotas) | Upload, analyze and interview requests fail with 500 (quotas fail closed) |
| 2 | [`migrations/20261106000005_analysis_claim.sql`](migrations/20261106000005_analysis_claim.sql) | `sessions.analysis_started_at` + `claim_analysis()` (one analysis run per session) | Every fresh analyze request fails with 500 |

(There is no `...003` file; the numbering gap is intentional.)

Both files only add objects (no data changes) and are safe to run on the live database. Each
function is executable by `service_role` only. Check afterwards:

```sql
select proname from pg_proc where proname in ('consume_quota', 'claim_analysis');  -- 2 rows
select column_name from information_schema.columns
 where table_name = 'sessions' and column_name = 'analysis_started_at';             -- 1 row
```

Delete the rows from this table once they are applied. The same SQL is smoke-tested on an
embedded Postgres by `supabase/tests/test_migrations.py` (CI).
