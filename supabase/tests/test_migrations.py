"""Smoke-test the Supabase migrations against an embedded Postgres + pgvector.

Run: pip install -r supabase/tests/requirements.txt && python supabase/tests/test_migrations.py
Simulates Supabase roles (anon, authenticated, service_role) and checks schema, RLS, grants,
cascade deletes and the hybrid_search RRF function. No Supabase account needed.
"""

import math
import pathlib
import random
import shutil
import sys
import tempfile

import pgserver
import psycopg

MIG_DIR = (
    pathlib.Path(sys.argv[1])
    if len(sys.argv) > 1
    else pathlib.Path(__file__).resolve().parent.parent / "migrations"
)
tmp = pathlib.Path(tempfile.mkdtemp(prefix="pgtest_"))
srv = pgserver.get_server(tmp, cleanup_mode="stop")
uri = srv.get_uri()

PREAMBLE = """
create schema if not exists extensions;
do $$ begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end $$;
grant usage on schema public, extensions to anon, authenticated, service_role;
-- mimic Supabase default grants (which our migration must revoke)
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
"""


def vec(seed: int, dim: int = 768) -> str:
    rnd = random.Random(seed)
    v = [rnd.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x * x for x in v))
    return "[" + ",".join(f"{x / n:.6f}" for x in v) + "]"


ok = True
with psycopg.connect(uri, autocommit=True) as conn:
    conn.execute(PREAMBLE)
    for f in sorted(MIG_DIR.glob("*.sql")):
        conn.execute(f.read_text(encoding="utf-8"))
        print("applied", f.name)

    conn.execute("grant all on all tables in schema public to service_role")
    rows = [
        ("python.md", 0, "python", "junior", "Python list comprehension generators and decorators explained"),
        ("python.md", 1, "python", "mid", "Python GIL, asyncio event loop and concurrency"),
        ("sql.md", 0, "sql", "all", "SQL joins: inner join, left join, and window functions"),
        ("nlp.md", 0, "nlp_llms", "junior", "Retrieval augmented generation with embeddings and vector search"),
    ]
    for i, (sf, ci, comp, lvl, content) in enumerate(rows):
        conn.execute(
            "insert into knowledge_chunks (source_file, chunk_index, competency, level, content, content_hash, embedding)"
            " values (%s,%s,%s,%s,%s,%s,%s::extensions.vector)",
            (sf, ci, comp, lvl, content, f"h{i}", vec(i)),
        )

    # Query whose embedding == RAG chunk embedding and text matches SQL chunk.
    res = conn.execute(
        "select content, competency, score from hybrid_search(%s::extensions.vector, %s, 3, %s::jsonb)",
        (vec(3), "window functions joins", "{}"),
    ).fetchall()
    print("knowledge results:", res)
    top2 = {r[1] for r in res[:2]}
    ok &= top2 == {"nlp_llms", "sql"}

    res = conn.execute(
        "select content, level from hybrid_search(%s::extensions.vector, %s, 5, %s::jsonb)",
        (vec(0), "python", '{"competency":"python","level":"junior"}'),
    ).fetchall()
    print("filtered python/junior:", res)
    ok &= len(res) == 1 and res[0][1] == "junior"

    # CV branch
    sid = conn.execute(
        "insert into sessions (guest_token_hash) values ('x') returning id"
    ).fetchone()[0]
    other = conn.execute("insert into sessions (guest_token_hash) values ('y') returning id").fetchone()[0]
    for s, txt in ((sid, "Built a FastAPI service with PostgreSQL"), (other, "Other user's secret CV")):
        did = conn.execute(
            "insert into documents (session_id, kind, raw_text, content_hash) values (%s,'cv',%s,'c') returning id",
            (s, txt),
        ).fetchone()[0]
        conn.execute(
            "insert into doc_chunks (document_id, chunk_index, content, embedding) values (%s,0,%s,%s::extensions.vector)",
            (did, txt, vec(42)),
        )
    res = conn.execute(
        "select content, document_id from hybrid_search(%s::extensions.vector, %s, 5, %s::jsonb)",
        (vec(42), "fastapi", f'{{"source":"cv","session_id":"{sid}"}}'),
    ).fetchall()
    print("cv results:", res)
    ok &= len(res) == 1 and "FastAPI" in res[0][0]

    try:
        conn.execute("select * from hybrid_search(%s::extensions.vector, 'x', 5, '{\"source\":\"cv\"}')", (vec(1),))
        ok = False
        print("FAIL: cv without session_id should raise")
    except psycopg.errors.RaiseException as e:
        print("cv without session raises:", str(e).splitlines()[0])

    # Cascade delete
    conn.execute("delete from sessions where id = %s", (sid,))
    left = conn.execute("select count(*) from doc_chunks").fetchone()[0]
    print("doc_chunks after deleting one session:", left)
    ok &= left == 1

    # anon must not read tables or call the function
    conn.execute("set role anon")
    for stmt in ("select * from knowledge_chunks", f"select * from hybrid_search('{vec(1)}'::extensions.vector,'x')"):
        try:
            conn.execute(stmt)
            ok = False
            print("FAIL: anon could run:", stmt[:40])
        except psycopg.errors.InsufficientPrivilege:
            print("anon denied:", stmt[:40])
    conn.execute("reset role")

    rls = conn.execute(
        "select count(*) from pg_tables where schemaname='public' and not rowsecurity"
    ).fetchone()[0]
    print("tables without RLS:", rls)
    ok &= rls == 0

srv.cleanup()
shutil.rmtree(tmp, ignore_errors=True)
print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
