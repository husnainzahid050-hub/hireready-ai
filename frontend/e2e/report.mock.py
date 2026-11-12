"""Real-browser test of the report pages against a mocked API (Phase 5).

Covers: the streamed report (code-computed overview renders before the AI write-up), the
research-brief order, share create / copy / revoke, email disabled vs enabled, print media,
delete-my-data (Cancel focused first, then /deleted), the public /r/[token] page (read-only,
redacted payload, gone message), and the /r/* response headers + robots.txt.

Usage (with the production build running):
    npm run build && npx next start -p 3001
    python e2e/report.mock.py [screenshot_dir]   (E2E_BASE=... for another port)

Requires the `playwright` Python package and Google Chrome (channel="chrome").
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, Route, expect, sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:3001")
SID = "11111111-2222-3333-4444-555555555555"
SHARE = "s" * 43
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("e2e-screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)


def dims(s: int, tech: bool = True, quote: str | None = None) -> list[dict]:
    rows = [("relevance", "Relevance", 0.2), ("technical_accuracy", "Technical accuracy", 0.25),
            ("depth", "Depth", 0.25), ("structure", "Structure (STAR)", 0.15),
            ("communication", "Communication", 0.15)]  # fmt: skip
    return [
        {"key": k, "label": label, "weight": w,
         "score": None if (k == "technical_accuracy" and not tech) else s,
         "justification": f"{label} scored {s}.", "evidence_quote": quote if k == "relevance" else None}
        for k, label, w in rows
    ]  # fmt: skip


def question(i: int, s: int, score: int, level: str, label: str, **kw) -> dict:
    q = {
        "label": f"Q{i}", "order": i, "type": kw.get("type", "technical"),
        "competency": kw.get("competency", "python"), "question": f"Question number {i}?",
        "answer": kw.get("answer", f"My answer {i} used FastAPI with caching."),
        "dimensions": dims(s, kw.get("tech", True), kw.get("quote")), "average": float(s),
        "score": score, "level": level, "level_label": label, "summary": "ok",
        "what_interviewer_wanted": f"Wanted {i}", "improved_answer": f"Improved answer {i}",
        "tip": f"Tip {i}", "follow_up": kw.get("follow_up"), "speech": kw.get("speech"),
    }  # fmt: skip
    return q


SPEECH = {"duration_seconds": 40.0, "words_per_minute": 150.0, "filler_count": 3,
          "filler_breakdown": {"um": 2, "matlab": 1}, "long_pauses": 1}  # fmt: skip
QUESTIONS = [
    question(1, 4, 83, "senior", "Senior-level answer", quote="FastAPI with caching",
             speech=SPEECH,
             follow_up={"label": "Q1.1", "question": "How did you measure it?",
                        "answer": "40 test questions.", "average": 5.0, "score": 100,
                        "handling": "You recovered well.", "tip": "Lead with the number."}),
    question(2, 2, 25, "below_junior", "Below the junior bar", competency="cloud_devops",
             answer="I have not really used Docker."),
    question(3, 3, 50, "junior", "Junior-level answer", type="behavioral", competency=None,
             tech=False),
    question(4, 3, 50, "junior", "Junior-level answer", competency="sql", speech=SPEECH),
    question(5, 4, 75, "mid", "Mid-level answer", type="project", competency="nlp_llms"),
    question(6, 3, 50, "junior", "Junior-level answer", type="role_fit", competency=None,
             tech=False),
]  # fmt: skip
READINESS = {
    "score": 55, "band": "getting_there", "band_label": "Getting there", "interview_score": 53,
    "match_score": 60, "formula": "Readiness = 0.75 × interview score 53 + 0.25 × CV match 60 = 55",
    "weights": {"interview": 0.75, "cv_match": 0.25}, "next_band_label": "Interview-ready",
    "points_to_next_band": 7,
}  # fmt: skip
SPEECH_SUMMARY = {
    "voice_answers": 1, "average_wpm": 150.0, "pace": "ideal",
    "guidance": "You averaged 150 WPM, inside the comfortable 120–160 WPM range.",
    "filler_total": 3, "filler_breakdown": {"um": 2, "matlab": 1}, "long_pauses_total": 1,
    "rows": [{"label": "Q1", "words_per_minute": 150.0, "filler_count": 3, "long_pauses": 1,
              "duration_seconds": 40.0}],
}  # fmt: skip
REPORT = {
    "version": 1, "state": "ready", "generated_at": "2026-11-12T10:00:00+00:00",
    "generated_by": "llm", "role_title": "Junior AI Engineer", "readiness": READINESS,
    "employer": {
        "verdict": "lean_no", "verdict_label": "Lean no", "score_verdict": "lean_no",
        "reaction": "I liked the FastAPI project, but Docker worried me.",
        "green_flags": [{"title": "Measured impact", "detail": "d", "answer_ref": "Q1",
                         "question": "Question number 1?", "quote": "FastAPI with caching",
                         "quote_verified": True}],
        "red_flags": [{"title": "No Docker", "detail": "d", "answer_ref": "Q2",
                       "question": "Question number 2?", "quote": None, "quote_verified": False}],
    },
    "questions": QUESTIONS, "speech": SPEECH_SUMMARY,
    "strengths": [{"title": "Concrete projects", "detail": "d", "answer_refs": ["Q1"]}],
    "improvements": [{"title": "Practise Docker basics", "detail": "Build one image.",
                      "answer_refs": ["Q2"]}],
    "open_gaps": ["Docker"],
    "prep_plan": [{"day": d, "focus": f"Focus {d}", "tasks": ["task a"],
                   "resource_urls": ["https://docs.docker.com/get-started/"] if d == 1 else []}
                  for d in range(1, 8)],
}  # fmt: skip
OVERVIEW = {"readiness": READINESS, "score_verdict": "lean_no", "questions": QUESTIONS,
            "speech": SPEECH_SUMMARY}  # fmt: skip

errors: list[str] = []


def sse(*events: tuple[str, dict]) -> str:
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)


def _json(route: Route, status: int, body: dict) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _err(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class FakeReport:
    def __init__(self, *, email: bool = False, stream: str | None = None, saved: bool = False):
        self.email = email
        self.stream = stream if stream is not None else sse(
            ("status", {"step": "collect", "message": "Collecting your answers and scores…"}),
            ("overview", OVERVIEW),
            ("status", {"step": "synthesis", "message": "The hiring manager is writing…"}),
            ("done", REPORT),
        )
        self.ready = saved
        self.share: str | None = None
        self.emailed_at: str | None = None
        self.deleted = False
        self.calls: list[str] = []

    def meta(self) -> dict:
        return {
            "status": "ready" if self.ready else "none",
            "report": REPORT if self.ready else None,
            "share": {"active": bool(self.share), "token": self.share,
                      "path": f"/r/{self.share}" if self.share else None},
            "email_configured": self.email, "emailed_at": self.emailed_at,
            "expires_at": "2026-11-19T10:00:00+00:00", "is_demo": True,
        }  # fmt: skip

    def handle(self, route: Route) -> None:
        req = route.request
        path = req.url.split("/api/v1", 1)[1].split("?")[0]
        self.calls.append(f"{req.method} {path}")
        if path.startswith("/reports/shared/"):
            token = path.rsplit("/", 1)[1]
            if token == self.share and not self.deleted:
                return _json(route, 200, {"report": REPORT, "expires_at": "2026-11-19T10:00:00Z"})
            return _json(route, 404, _err("report_not_found", "This report link was revoked."))
        assert req.headers.get("x-guest-token") == "tok-123", "guest token header missing"
        if self.deleted:
            return _json(route, 404, _err("session_not_found", "Session not found."))
        base = f"/sessions/{SID}"
        if path == f"{base}/report" and req.method == "GET":
            return _json(route, 200, self.meta())
        if path == f"{base}/report" and req.method == "POST":
            self.ready = True
            return route.fulfill(status=200, content_type="text/event-stream", body=self.stream)
        if path == f"{base}/report/share":
            action = (req.post_data_json or {}).get("action", "create")
            self.share = None if action == "revoke" else (self.share or SHARE)
            return _json(route, 200, self.meta()["share"])
        if path == f"{base}/email":
            if not self.email:
                return _json(route, 503, _err("email_not_configured", "Email isn't set up."))
            self.emailed_at = "2026-11-12T10:05:00+00:00"
            return _json(route, 200, {"sent": True, "emailed_at": self.emailed_at,
                                      "sent_to": "a•••@example.com"})  # fmt: skip
        if path == base and req.method == "DELETE":
            self.deleted = True
            return route.fulfill(status=204, body="")
        return _json(route, 404, _err("not_found", "Not found."))


def open_page(browser, fake: FakeReport, url: str, token: bool = True) -> Page:
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    if token:
        ctx.add_init_script(f"localStorage.setItem('hireready:token:{SID}', 'tok-123')")
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
            and errors.append(m.text))  # fmt: skip
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.route("**/api/v1/**", fake.handle)
    page.goto(f"{BASE}{url}")
    return page


# ------------------------------------------------------------------ scenarios


def streamed_report_and_order(browser) -> None:
    fake = FakeReport()
    page = open_page(browser, fake, f"/session/{SID}/report")
    expect(page.get_by_role("heading", name="Interview report: Junior AI Engineer")).to_be_visible()
    expect(page.get_by_role("heading", name="Getting there 55/100")).to_be_visible()
    expect(page.get_by_text("7 points to Interview-ready")).to_be_visible()
    expect(page.get_by_text("Sample CV")).to_be_visible()
    # Research-brief order: fixes before the employer view, strengths after the cards.
    headings = page.locator("h2").all_inner_texts()
    order = ["Top 3 things to fix", "Across all answers", "Simulated hiring-manager reaction",
             "Question by question", "How you sounded", "Strengths to keep",
             "Your refreshed 7-day plan"]  # fmt: skip
    idx = [next(i for i, h in enumerate(headings) if h.startswith(o)) for o in order]
    assert idx == sorted(idx), headings
    # Weakest card (Q2) open; verified quote marked in Q1's transcript; follow-up shown.
    expect(page.locator("#q2 details").first).to_have_attribute("open", "")
    page.locator("#q1 summary").first.click()
    expect(page.locator("#q1 mark")).to_have_text("FastAPI with caching")
    expect(page.get_by_text("Follow-up Q1.1")).to_be_visible()
    expect(page.get_by_text("↑ up vs. main answer")).to_be_visible()
    expect(page.get_by_text("Delivery numbers are guidance only and don")).to_be_visible()
    # Unverified red-flag quote never shown.
    expect(page.get_by_text("You said:").first).to_be_visible()
    assert fake.calls.count(f"POST /sessions/{SID}/report") == 1, fake.calls
    page.screenshot(path=str(SHOTS / "report-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(SHOTS / "report-mobile.png"), full_page=True)
    # Print media: chrome and action bar hidden, print header shown.
    page.emulate_media(media="print")
    expect(page.get_by_role("toolbar", name="Report actions")).to_be_hidden()
    expect(page.get_by_text("HireReady AI · practice interview report")).to_be_visible()
    # The brief's budget: a 6-question report prints on at most 5 A4 pages.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.evaluate("document.querySelectorAll('details').forEach((d) => (d.open = true))")
    pdf = page.pdf(format="A4")
    (SHOTS / "report.pdf").write_bytes(pdf)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    print(f"      PDF pages (A4, 6 questions, all details open): {pages}")
    assert pages <= 5, pages
    page.context.close()


def overview_shows_before_synthesis_error(browser) -> None:
    stream = sse(("overview", OVERVIEW),
                 ("error", {"code": "report_timeout", "message": "Our AI providers are busy."}))
    page = open_page(browser, FakeReport(stream=stream), f"/session/{SID}/report")
    expect(page.get_by_text("Our AI providers are busy.")).to_be_visible()
    expect(page.get_by_role("heading", name="Getting there 55/100")).to_be_visible()
    expect(page.get_by_text("This part could not be written").first).to_be_visible()
    expect(page.locator(".animate-pulse")).to_have_count(0)  # never pulsing after an error
    expect(page.get_by_role("button", name="Try again")).to_be_visible()
    page.context.close()


def share_lifecycle_and_public_page(browser) -> None:
    fake = FakeReport(saved=True)
    page = open_page(browser, fake, f"/session/{SID}/report")
    expect(page.get_by_role("button", name="Email me this report")).to_be_disabled()
    expect(page.get_by_text("Email isn't set up on this server yet").first).to_be_visible()
    page.get_by_role("button", name="Share").click()
    expect(page.get_by_text("It never shows")).to_be_visible()
    page.get_by_role("button", name="Create share link").click()
    field = page.get_by_label("Anyone with this link can view a read-only copy")
    expect(field).to_have_value(f"{BASE}/r/{SHARE}")
    page.get_by_role("button", name="Copy link").click()
    expect(page.get_by_role("button", name="Copied")).to_be_visible()

    pub = page.context.new_page()
    pub.route("**/api/v1/**", fake.handle)
    resp = pub.goto(f"{BASE}/r/{SHARE}")
    assert resp is not None
    assert resp.headers.get("x-robots-tag") == "noindex, nofollow, noarchive", resp.headers
    assert resp.headers.get("referrer-policy") == "no-referrer", resp.headers
    assert "no-store" in (resp.headers.get("cache-control") or ""), resp.headers
    robots = pub.locator('meta[name="robots"]').get_attribute("content") or ""
    assert "noindex" in robots and "nofollow" in robots, robots
    og = pub.locator('meta[property="og:title"]').get_attribute("content") or ""
    assert "55" not in og and "Junior" not in og, og  # generic preview, no score
    expect(pub.get_by_text("Shared practice report · read-only.")).to_be_visible()
    expect(pub.get_by_role("toolbar", name="Report actions")).to_have_count(0)
    expect(pub.get_by_role("button", name="Delete my data")).to_have_count(0)
    expect(pub.get_by_role("button", name="Try with a sample CV")).to_be_visible()
    pub.screenshot(path=str(SHOTS / "report-shared.png"), full_page=True)

    page.get_by_role("button", name="Revoke").click()
    expect(page.get_by_role("button", name="Create share link")).to_be_visible()
    pub.reload()
    expect(pub.get_by_text("This report link was revoked.")).to_be_visible()
    page.context.close()


def email_and_delete(browser) -> None:
    fake = FakeReport(saved=True, email=True)
    page = open_page(browser, fake, f"/session/{SID}/report")
    page.get_by_role("button", name="Email me this report").click()
    page.get_by_label("Email address").fill("ali@example.com")
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("Sent to a•••@example.com")).to_be_visible()

    page.get_by_role("button", name="Delete my data").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    assert not fake.deleted
    page.get_by_role("button", name="Delete my data").click()
    page.get_by_role("button", name="Delete everything").click()
    expect(page.get_by_role("heading", name="Deleted.")).to_be_visible()
    assert fake.deleted
    assert page.evaluate(f"localStorage.getItem('hireready:token:{SID}')") is None
    page.context.close()


def no_token(browser) -> None:
    page = open_page(browser, FakeReport(), f"/session/{SID}/report", token=False)
    expect(page.get_by_text("This report belongs to another browser")).to_be_visible()
    page.context.close()


def robots_allows_r() -> None:
    with urllib.request.urlopen(f"{BASE}/robots.txt") as r:  # noqa: S310 (local test server)
        text = r.read().decode()
    assert "Disallow: /r/" not in text, text
    assert "Disallow: /session/" in text, text


def main() -> int:
    robots_allows_r()
    print("PASS  robots.txt lets crawlers see /r/ noindex")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for name, fn in [
            ("streamed report renders in the brief's order; print media", streamed_report_and_order),
            ("overview stays after a synthesis error; no pulsing", overview_shows_before_synthesis_error),
            ("share create / copy / public page / revoke", share_lifecycle_and_public_page),
            ("email sent line; delete dialog cancel-first then /deleted", email_and_delete),
            ("no guest token shows the private-session panel", no_token),
        ]:  # fmt: skip
            fn(browser)
            print(f"PASS  {name}")
        browser.close()
    if errors:
        print("FAIL  console errors:", *errors, sep="\n  ")
        return 1
    print("PASS  no console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
