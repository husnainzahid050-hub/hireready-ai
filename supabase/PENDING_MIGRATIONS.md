# Pending migrations (apply before deploying the current backend)

The live Supabase project has `20261106000001_init_schema.sql` and
`20261106000002_hybrid_search.sql`. Paste these files into the Supabase **SQL editor** and run
them **in this order**, one at a time:

| # | File | What it adds | Without it |
|---|---|---|---|
| 1 | [`migrations/20261106000004_security.sql`](migrations/20261106000004_security.sql) | `session_usage` table + `consume_quota()` (per-session quotas) | Upload, analyze and interview requests fail with 500 (quotas fail closed) |
| 2 | [`migrations/20261106000005_analysis_claim.sql`](migrations/20261106000005_analysis_claim.sql) | `sessions.analysis_started_at` + `claim_analysis()` (one analysis run per session) | Every fresh analyze request fails with 500 |
| 3 | [`migrations/20261112000007_phase7_automation.sql`](migrations/20261112000007_phase7_automation.sql) | `sessions.reminders_opt_in`; replaces the never-used `reminders` placeholder with the Phase 7 table; `cron_runs`; `cleanup_expired()`; `copy_demo_analysis()` | Cleanup cron fails (500), demo cache misses (demo still works, with LLM calls), ticking "Send me 7 daily prep emails" makes session creation fail |

(There is no `...003` file; the numbering gap is intentional. Phase 5 (report, share links,
email, delete) needs **no new SQL**: it uses the `reports` table and the cascades from the first
migration.)

Files 1-2 only add objects. File 3 also **drops** the Phase 1 `reminders` table, which nothing
ever wrote to (check first: `select count(*) from reminders;` should be 0). All are safe to run on
the live database. Each
function is executable by `service_role` only. Check afterwards:

```sql
select proname from pg_proc where proname in ('consume_quota', 'claim_analysis');  -- 2 rows
select column_name from information_schema.columns
 where table_name = 'sessions' and column_name = 'analysis_started_at';             -- 1 row
select proname from pg_proc where proname in ('cleanup_expired', 'copy_demo_analysis');  -- 2 rows
select column_name from information_schema.columns
 where table_name = 'reminders' and column_name = 'token_hash';                     -- 1 row
```

Delete the rows from this table once they are applied. The same SQL is smoke-tested on an
embedded Postgres by `supabase/tests/test_migrations.py` (CI).
