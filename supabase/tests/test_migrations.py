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
import threading
import time

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

    # Per-session quotas (20261106000004_security.sql): atomic, capped, cascade-deleted.
    results = [
        conn.execute("select consume_quota(%s, 'analysis', 2)", (other,)).fetchone()[0]
        for _ in range(3)
    ]
    print("consume_quota x3 with limit 2:", results)
    ok &= results == [True, True, False]
    used = conn.execute(
        "select count from session_usage where session_id = %s and action = 'analysis'", (other,)
    ).fetchone()[0]
    ok &= used == 2
    ok &= conn.execute("select consume_quota(%s, 'upload', 0)", (other,)).fetchone()[0] is False

    # Analysis claim (20261106000005_analysis_claim.sql): once per session, stale claims expire,
    # and a session that already has a saved analysis can't be claimed.
    claim = "select claim_analysis(%s, %s)"
    claims = [conn.execute(claim, (other, 120)).fetchone()[0] for _ in range(2)]
    print("claim_analysis twice:", claims)
    ok &= claims == [True, False]
    conn.execute(
        "update sessions set analysis_started_at = now() - interval '10 minutes' where id = %s",
        (other,),
    )
    # Two connections racing: B blocks on A's row lock, re-checks after A commits, and loses.
    conn.execute("update sessions set analysis_started_at = null where id = %s", (other,))
    with psycopg.connect(uri) as a, psycopg.connect(uri) as b:
        won_a = a.execute(claim, (other, 120)).fetchone()[0]  # A's transaction stays open
        result_b: list[bool] = []
        t = threading.Thread(target=lambda: result_b.append(b.execute(claim, (other, 120)).fetchone()[0]))
        t.start()
        time.sleep(0.5)
        blocked = t.is_alive()
        a.commit()
        t.join(10)
        b.commit()
    print("concurrent claims (A, B blocked, B):", won_a, blocked, result_b)
    ok &= won_a is True and blocked and result_b == [False]
    conn.execute(
        "update sessions set analysis_started_at = now() - interval '10 minutes' where id = %s",
        (other,),
    )
    stale = conn.execute(claim, (other, 120)).fetchone()[0]
    print("stale claim taken over:", stale)
    ok &= stale is True
    conn.execute("update sessions set analysis_started_at = null where id = %s", (other,))
    conn.execute(
        "insert into gap_analyses (session_id, match_score, breakdown, gaps, strengths,"
        " likely_questions, prep_plan) values (%s, 50, '{}', '[]', '[]', '[]', '[]')",
        (other,),
    )
    analyzed = conn.execute(claim, (other, 120)).fetchone()[0]
    unknown = conn.execute(claim, ("00000000-0000-0000-0000-000000000000", 120)).fetchone()[0]
    print("claim when analyzed / unknown session:", analyzed, unknown)
    ok &= analyzed is False and unknown is False

    # Report claim (Phase 5, app/services/report.py): the reports primary key IS the lock, so a
    # second placeholder insert must fail; share tokens are unique; a JSON-path filter deletes
    # only the placeholder; the report row is cascade-deleted with the session.
    ins = "insert into reports (session_id, report, share_token) values (%s, %s::jsonb, %s)"
    conn.execute(ins, (other, '{"state": "generating"}', None))
    try:
        conn.execute(ins, (other, '{"state": "generating"}', None))
        ok = False
        print("FAIL: second report claim should violate the primary key")
    except psycopg.errors.UniqueViolation:
        print("second report claim rejected (pk)")
    conn.execute("update reports set report = '{\"state\": \"ready\"}', share_token = 'tok1' where session_id = %s", (other,))
    conn.execute("delete from reports where session_id = %s and report->>'state' = 'generating'", (other,))
    ok &= conn.execute("select count(*) from reports").fetchone()[0] == 1  # ready row kept
    third = conn.execute(
        "insert into sessions (guest_token_hash) values ('h3') returning id"
    ).fetchone()[0]
    try:
        conn.execute(ins, (third, "{}", "tok1"))
        ok = False
        print("FAIL: share_token should be unique")
    except psycopg.errors.UniqueViolation:
        print("duplicate share token rejected")

    conn.execute("delete from sessions where id in (%s, %s)", (other, third))
    reports_left = conn.execute("select count(*) from reports").fetchone()[0]
    print("reports after deleting the session:", reports_left)
    ok &= reports_left == 0
    usage_left = conn.execute("select count(*) from session_usage").fetchone()[0]
    print("session_usage rows after deleting the session:", usage_left)
    ok &= usage_left == 0

    # Phase 7 (20261112000007_phase7_automation.sql) ---------------------------------------
    # cleanup_expired: an expired session with EVERY child type is fully deleted, its running
    # reminder survives (detached), a live session is untouched, expired reminders go, a run is
    # recorded, and a second run is a no-op.
    def session(expired: bool, demo: bool = False) -> str:
        when = "now() - interval '1 day'" if expired else "now() + interval '7 days'"
        return conn.execute(
            f"insert into sessions (guest_token_hash, expires_at, is_demo, reminders_opt_in)"
            f" values ('h', {when}, %s, true) returning id",
            (demo,),
        ).fetchone()[0]

    def full_session(expired: bool) -> str:
        s = session(expired)
        did = conn.execute(
            "insert into documents (session_id, kind, raw_text, content_hash) values (%s,'cv','t','c') returning id",
            (s,),
        ).fetchone()[0]
        conn.execute(
            "insert into doc_chunks (document_id, chunk_index, content, embedding) values (%s,0,'t',%s::extensions.vector)",
            (did, vec(7)),
        )
        conn.execute(
            "insert into gap_analyses (session_id, match_score, breakdown, gaps, strengths,"
            " likely_questions, prep_plan) values (%s, 50, '{}', '[]', '[]', '[]', '[]')",
            (s,),
        )
        qid = conn.execute(
            "insert into questions (session_id, order_index, type, text) values (%s, 1, 'technical', 'q') returning id",
            (s,),
        ).fetchone()[0]
        conn.execute("insert into answers (question_id, transcript) values (%s, 'a')", (qid,))
        conn.execute("insert into interview_state (session_id, state) values (%s, '{}')", (s,))
        conn.execute("insert into reports (session_id, report) values (%s, '{}')", (s,))
        conn.execute("select consume_quota(%s, 'upload', 5)", (s,))
        return s

    def reminder(sid: str | None, nonce: str, expires: str = "now() + interval '5 days'") -> None:
        conn.execute(
            "insert into reminders (session_id, email, email_hash, plan, token_nonce, token_hash,"
            f" status, expires_at) values (%s, 'a@b.co', %s, '[]', %s, %s, 'active', {expires})",
            (sid, "e" * 64, nonce, nonce.ljust(64, "0")),
        )

    expired_sid, live_sid = full_session(True), full_session(False)
    reminder(expired_sid, "nonce-expired-session-0001")
    reminder(None, "nonce-expired-reminder-0002", "now() - interval '1 hour'")
    stats = conn.execute("select cleanup_expired(200)").fetchone()[0]
    print("cleanup stats:", stats)
    ok &= stats["sessions"] == 1 and stats["answers"] == 1 and stats["doc_chunks"] == 1
    ok &= stats["reminders"] == 1 and stats["session_usage"] == 1 and stats["more"] is False
    for table in ("documents", "doc_chunks", "gap_analyses", "questions", "answers",
                  "interview_state", "reports", "session_usage"):  # fmt: skip
        col = "document_id" if table == "doc_chunks" else "question_id" if table == "answers" else None
        if col is None:
            left = conn.execute(f"select count(*) from {table} where session_id = %s", (expired_sid,)).fetchone()[0]
        else:
            left = conn.execute(f"select count(*) from {table}").fetchone()[0] - 1  # live session's row
        ok &= left == 0
        if left:
            print("FAIL: cleanup left rows in", table)
    kept = conn.execute("select session_id from reminders where token_nonce = 'nonce-expired-session-0001'").fetchone()
    print("reminder of the expired session kept, detached:", kept)
    ok &= kept is not None and kept[0] is None
    ok &= conn.execute("select count(*) from sessions where id = %s", (live_sid,)).fetchone()[0] == 1
    again = conn.execute("select cleanup_expired(200)").fetchone()[0]
    ok &= again["sessions"] == 0 and again["reminders"] == 0
    runs = conn.execute("select count(*) from cron_runs where name = 'cleanup'").fetchone()[0]
    print("cron_runs rows:", runs)
    ok &= runs == 2

    # "Delete my data" still deletes the reminder (cascade); one reminder per session.
    reminder(live_sid, "nonce-live-session-00003")
    try:
        reminder(live_sid, "nonce-live-session-00004")
        ok = False
        print("FAIL: second reminder for one session should be rejected")
    except psycopg.errors.UniqueViolation:
        print("second reminder per session rejected")
    conn.execute("delete from sessions where id = %s", (live_sid,))
    ok &= conn.execute("select count(*) from reminders where token_nonce like 'nonce-live%%'").fetchone()[0] == 0

    # copy_demo_analysis: copies profiles, chunks (with embeddings) and the analysis from an
    # earlier demo session with the same CV + JD; never from a non-demo or different text.
    def demo_docs(s: str, cv_hash: str, structured: bool) -> None:
        for kind, h in (("cv", cv_hash), ("jd", "jdhash")):
            conn.execute(
                "insert into documents (session_id, kind, raw_text, content_hash, structured)"
                " values (%s, %s, 't', %s, %s::jsonb)",
                (s, kind, h, '{"name": "Ali"}' if structured else None),
            )

    src = session(False, demo=True)
    demo_docs(src, "cvhash", True)
    src_cv = conn.execute("select id from documents where session_id = %s and kind = 'cv'", (src,)).fetchone()[0]
    conn.execute(
        "insert into doc_chunks (document_id, chunk_index, content, embedding) values (%s,0,'demo chunk',%s::extensions.vector)",
        (src_cv, vec(9)),
    )
    conn.execute(
        "insert into gap_analyses (session_id, match_score, breakdown, gaps, strengths,"
        " likely_questions, prep_plan) values (%s, 64, '{}', '[]', '[]', '[]', '[]')",
        (src,),
    )
    conn.execute("update sessions set role_title = 'Junior AI Engineer' where id = %s", (src,))
    dst, other_cv, not_demo = session(False, demo=True), session(False, demo=True), session(False)
    demo_docs(dst, "cvhash", False)
    demo_docs(other_cv, "different", False)
    demo_docs(not_demo, "cvhash", False)
    copied = [conn.execute("select copy_demo_analysis(%s)", (s,)).fetchone()[0] for s in (dst, dst, other_cv, not_demo)]
    print("copy_demo_analysis (dst, dst again, other CV, not demo):", copied)
    ok &= copied == [True, False, False, False]
    row = conn.execute(
        "select s.status, s.role_title, g.match_score, (select count(*) from doc_chunks c join documents d"
        " on d.id = c.document_id where d.session_id = s.id), (select structured->>'name' from documents"
        " where session_id = s.id and kind = 'cv') from sessions s join gap_analyses g on g.session_id = s.id"
        " where s.id = %s",
        (dst,),
    ).fetchone()
    print("copied demo session:", row)
    ok &= row == ("analyzed", "Junior AI Engineer", 64, 1, "Ali")

    # anon must not read tables or call the functions
    conn.execute("set role anon")
    for stmt in (
        "select * from knowledge_chunks",
        "select * from session_usage",
        "select * from reminders",
        "select * from cron_runs",
        "select cleanup_expired(10)",
        "select copy_demo_analysis(gen_random_uuid())",
        f"select * from hybrid_search('{vec(1)}'::extensions.vector,'x')",
        "select consume_quota(gen_random_uuid(), 'x', 5)",
        "select claim_analysis(gen_random_uuid(), 60)",
    ):
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
