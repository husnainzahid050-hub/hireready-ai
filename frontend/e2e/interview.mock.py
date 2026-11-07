"""Real-browser test of the interview page (text mode) against a mocked API.

The backend is not needed: every /api/v1/** request is answered by an in-test fake that follows
the Phase 3 interview contract (InterviewTurn, error envelope, 409/400/429/503 codes).

Usage (with the production build running):
    npm run build && npx next start -p 3001
    python e2e/interview.mock.py [screenshot_dir]   (E2E_BASE=... for another port)

Requires the `playwright` Python package and Google Chrome (channel="chrome").
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, Route, expect, sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:3001")
SID = "11111111-2222-3333-4444-555555555555"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("e2e-screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

PLAN = [
    ("technical", "Python", "Walk me through how you'd structure a small FastAPI service."),
    ("technical", "SQL", "How would you find duplicate rows in a Postgres table?"),
    ("project", None, "Tell me about the RAG chatbot on your CV. What did you build yourself?"),
    ("gap_probe", "Docker", "The role uses Docker daily. How have you containerised an app?"),
    ("behavioral", None, "Describe a time a deadline slipped. What did you do?"),
    ("role_fit", None, "Why this junior AI engineer role, and why now?"),
]
FOLLOW_UP_AFTER = 2  # a follow-up is asked after main question #2
FOLLOW_UP_TEXT = "You mentioned GROUP BY. How would you then delete all but one?"


class FakeInterview:
    """Minimal server-side state machine for the interview endpoints."""

    def __init__(self) -> None:
        self.started = False
        self.practice = False
        self.queue: list[dict] = []
        self.history: list[dict] = []
        self.last_answer: dict | None = None
        self.fail_next: list[tuple[int, str, dict]] = []  # (status, code, headers)
        self.hold_next = False
        self.held: list[Route] = []
        self.calls: list[str] = []

    def _plan(self) -> None:
        for i, (t, comp, text) in enumerate(PLAN, start=1):
            self.queue.append(
                {"id": f"q{i}", "order": i, "type": t, "competency": comp, "text": text,
                 "is_follow_up": False}
            )
            if i == FOLLOW_UP_AFTER:
                self.queue.append(
                    {"id": f"q{i}f", "order": i, "type": "follow_up", "competency": comp,
                     "text": FOLLOW_UP_TEXT,
                     "is_follow_up": True}
                )

    def turn(self, full_history: bool = True) -> dict:
        """Mirror the real contract: `history` only on GET ([] on POSTs); `answered` counts
        main questions only (follow-ups excluded)."""
        q = self.queue[0] if self.queue else None
        main_answered = sum(1 for h in self.history if not h["question"]["is_follow_up"])
        return {
            "status": "interviewing" if q else "completed",
            "practice_mode": self.practice,
            "progress": {"answered": main_answered, "total_planned": len(PLAN)},
            "question": q,
            "last_answer": self.last_answer,
            "history": list(self.history) if full_history else [],
        }

    def answer(self, text: str) -> None:
        q = self.queue.pop(0)
        self.history.append({"question": q, "answer_text": text})
        fb = (
            {"summary": f"Clear answer on {q['competency'] or q['type']}.",
             "tip": "Add one concrete number to show impact."}
            if self.practice else None
        )
        self.last_answer = {"question_id": q["id"], "transcript": text, "feedback": fb}

    # ------------------------------------------------------------------ routing
    def handle(self, route: Route) -> None:
        req = route.request
        path = req.url.split("/api/v1", 1)[1].split("?")[0]
        self.calls.append(f"{req.method} {path}")
        assert req.headers.get("x-guest-token") == "tok-123", "guest token header missing"

        if path == f"/sessions/{SID}/analysis":
            return _json(route, 200, {"analysis": SAMPLE_ANALYSIS})
        if not path.startswith(f"/sessions/{SID}/interview"):
            return _json(route, 404, _err("not_found", "Not found."))

        if self.fail_next and req.method == "POST":
            status, code, headers = self.fail_next.pop(0)
            return _json(route, status, _err(code, f"simulated {code}"), headers)

        if req.method == "GET":
            if not self.started:
                return _json(route, 409, _err("not_started", "Interview not started."))
            return _json(route, 200, self.turn())
        if path.endswith("/start"):
            if not self.started:
                self.started = True
                self.practice = bool(req.post_data_json["practice_mode"])
                self._plan()
            return _json(route, 200, self.turn(full_history=False))
        if path.endswith("/answer"):
            body = req.post_data_json
            assert 1 <= len(body["text"]) <= 5000
            if not self.queue:
                return _json(route, 409, _err("interview_completed", "Already completed."))
            if body["question_id"] != self.queue[0]["id"]:
                return _json(route, 400, _err("wrong_question", "Not the current question."))
            if self.hold_next:  # let the test observe the optimistic "thinking" state
                self.hold_next = False
                self.held.append(route)
                return None
            self.answer(body["text"])
            return _json(route, 200, self.turn(full_history=False))
        return _json(route, 404, _err("not_found", "Not found."))

    def release_held(self) -> None:
        route = self.held.pop(0)
        self.answer(route.request.post_data_json["text"])
        _json(route, 200, self.turn(full_history=False))


def _err(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _json(route: Route, status: int, body: dict, headers: dict | None = None) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body),
                  headers=headers or {})


SAMPLE_ANALYSIS = {
    "role_title": "Junior AI Engineer",
    "match_score": 72,
    "breakdown": {
        "formula": "100 x (0.7 x must + 0.2 x nice + 0.1 x seniority)",
        "must_have": {"weight": 0.7, "score": 0.7, "detail": "7 of 10"},
        "nice_to_have": {"weight": 0.2, "score": 0.5, "detail": "1 of 2"},
        "seniority_fit": {"weight": 0.1, "score": 1.0, "detail": "Junior"},
    },
    "gaps": [], "strengths": [], "likely_questions": [], "prep_plan": [],
}

# ---------------------------------------------------------------------- helpers

console_errors: list[str] = []
expected_http_errors: list[str] = []


def new_page(browser, *, viewport, token=True, dark=False) -> Page:
    ctx = browser.new_context(viewport=viewport, color_scheme="dark" if dark else "light",
                              reduced_motion="reduce" if dark else "no-preference")
    if token:
        ctx.add_init_script(f"localStorage.setItem('hireready:token:{SID}', 'tok-123')")
    page = ctx.new_page()

    def on_console(msg):
        if msg.type != "error":
            return
        # Browsers log every non-2xx fetch; those are the errors this test provokes on purpose.
        if "Failed to load resource" in msg.text:
            expected_http_errors.append(msg.text)
        else:
            console_errors.append(msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
    return page


def answer_box(page: Page):
    return page.get_by_label("Your answer")


def send(page: Page, text: str, *, keyboard=False) -> None:
    answer_box(page).fill(text)
    if keyboard:
        answer_box(page).press("Control+Enter")
    else:
        page.get_by_role("button", name="Send answer").click()


def expect_question(page: Page, text: str) -> None:
    expect(page.locator("#current-question-label + p")).to_have_text(text)


def no_horizontal_scroll(page: Page) -> None:
    w = page.evaluate("document.documentElement.scrollWidth")
    vw = page.viewport_size["width"]
    assert w <= vw, f"horizontal overflow: {w} > {vw}"


# ---------------------------------------------------------------------- scenarios

def desktop_flow(browser) -> None:
    fake = FakeInterview()
    page = new_page(browser, viewport={"width": 1280, "height": 900})
    page.route("**/api/v1/**", fake.handle)

    # Analysis page CTA links to the interview.
    page.goto(f"{BASE}/session/{SID}/analysis")
    cta = page.get_by_role("link", name="Start interview")
    expect(cta).to_have_attribute("href", f"/session/{SID}/interview")
    cta.click()
    page.wait_for_url(f"**/session/{SID}/interview")

    # Start screen (GET -> 409 not_started).
    expect(page.get_by_role("heading", name="Ready for your mock interview?")).to_be_visible()
    switch = page.get_by_role("switch", name="Practice mode")
    expect(switch).not_to_be_checked()
    switch.focus()
    page.keyboard.press("Space")
    expect(switch).to_be_checked()
    page.screenshot(path=str(SHOTS / "desktop-1-start.png"), full_page=True)
    page.get_by_role("button", name="Start interview").click()

    # Q1: keyboard submit, with the optimistic "thinking" state held open.
    expect_question(page, PLAN[0][2])
    expect(page.get_by_text("Question 1 of ~6")).to_be_visible()
    expect(answer_box(page)).to_be_focused()
    fake.hold_next = True
    send(page, "I'd split routers, schemas and services, with dependency injection for the DB.",
         keyboard=True)
    expect(page.get_by_text("Interviewer is thinking…", exact=True)).to_be_visible()
    expect(page.locator("[aria-live=polite][aria-atomic=true]")).to_have_text(
        "Answer sent. The interviewer is thinking…")
    expect(page.get_by_role("button", name="Sending…")).to_be_disabled()
    expect(answer_box(page)).to_have_attribute("readonly", "")
    expect(page.locator("#transcript-list").get_by_text("Sending…")).to_be_visible()
    page.screenshot(path=str(SHOTS / "desktop-2-thinking.png"), full_page=True)
    fake.release_held()

    # Q2 + practice feedback card; then the follow-up.
    expect_question(page, PLAN[1][2])
    expect(page.get_by_role("heading", name="Practice feedback on your last answer")).to_be_visible()
    expect(answer_box(page)).to_have_value("")
    send(page, "GROUP BY the columns and HAVING count(*) > 1.")
    expect_question(page, FOLLOW_UP_TEXT)
    expect(page.get_by_text("Question 2 of ~6")).to_be_visible()
    expect(page.locator("main").get_by_text("Follow-up", exact=True)).to_be_visible()
    page.screenshot(path=str(SHOTS / "desktop-3-follow-up.png"), full_page=True)
    send(page, "Use a CTE with row_number() and delete where rn > 1.")
    expect_question(page, PLAN[2][2])

    # Reload mid-interview: resumes via GET with history and restores the unsent draft.
    answer_box(page).fill("Draft that must survive a reload")
    page.reload()
    expect_question(page, PLAN[2][2])
    expect(page.get_by_text("Question 3 of ~6")).to_be_visible()
    expect(page.locator("#transcript-list > ol > li")).to_have_count(3)
    expect(answer_box(page)).to_have_value("Draft that must survive a reload")

    # 503 ai_unavailable: the text is kept and "Retry" resubmits it.
    fake.fail_next.append((503, "ai_unavailable", {}))
    q3 = "I built the retrieval layer: chunking, pgvector search and reranking."
    send(page, q3)
    expect(page.locator("main").get_by_role("alert")).to_contain_text("temporarily unavailable")
    expect(answer_box(page)).to_have_value(q3)
    page.screenshot(path=str(SHOTS / "desktop-4-503.png"), full_page=True)
    page.get_by_role("button", name="Retry sending answer").click()
    expect_question(page, PLAN[3][2])
    assert fake.history[-1]["answer_text"] == q3

    # 429 with Retry-After: friendly wait, send blocked, then allowed again.
    fake.fail_next.append((429, "rate_limited", {"Retry-After": "2"}))
    q4 = "I wrote a multi-stage Dockerfile for a FastAPI app."
    send(page, q4)
    expect(page.get_by_text("You're going a little fast", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Send answer")).to_be_disabled()
    expect(answer_box(page)).to_have_value(q4)
    page.screenshot(path=str(SHOTS / "desktop-5-429.png"), full_page=True)
    expect(page.get_by_role("button", name="Send answer")).to_be_enabled(timeout=5000)
    page.get_by_role("button", name="Send answer").click()
    expect_question(page, PLAN[4][2])

    # wrong_question: another tab answered first -> the page refetches the state.
    fake.answer("Answered in another tab.")
    send(page, "A deadline slipped; I re-scoped and told the team early.")
    expect(page.get_by_text("interview had moved on", exact=False)).to_be_visible()
    expect_question(page, PLAN[5][2])

    send(page, "It matches my RAG projects and I want to ship real AI features.")
    expect(page.get_by_role("heading", name="Interview complete. Nice work!")).to_be_visible()
    expect(page.get_by_role("link", name="Back to your analysis")).to_have_attribute(
        "href", f"/session/{SID}/analysis")
    page.screenshot(path=str(SHOTS / "desktop-6-complete.png"), full_page=True)
    page.context.close()


def mobile_flow(browser, *, dark: bool) -> None:
    fake = FakeInterview()
    page = new_page(browser, viewport={"width": 390, "height": 844}, dark=dark)
    page.route("**/api/v1/**", fake.handle)
    tag = "mobile-dark" if dark else "mobile"

    page.goto(f"{BASE}/session/{SID}/interview")
    expect(page.get_by_role("button", name="Start interview")).to_be_visible()
    no_horizontal_scroll(page)
    page.screenshot(path=str(SHOTS / f"{tag}-1-start.png"), full_page=True)
    page.get_by_role("button", name="Start interview").click()  # realistic mode

    for i in range(len(PLAN) + 1):  # 6 questions + 1 follow-up
        expect(answer_box(page)).to_be_visible()
        if i == 2:
            expect(page.locator("main").get_by_text("Follow-up", exact=True)).to_be_visible()
            # Transcript is collapsed on mobile; the disclosure opens it.
            toggle = page.get_by_role("button", name="Transcript (2)")
            expect(toggle).to_have_attribute("aria-expanded", "false")
            expect(page.locator("#transcript-list")).to_be_hidden()
            toggle.click()
            expect(page.locator("#transcript-list")).to_be_visible()
            no_horizontal_scroll(page)
            page.screenshot(path=str(SHOTS / f"{tag}-2-follow-up.png"), full_page=True)
        send(page, f"Mobile answer number {i + 1} with enough detail.")
        if i < len(PLAN):
            expect(page.locator("#transcript-list > ol > li")).to_have_count(i + 1)
        # Realistic mode never shows per-answer feedback.
        expect(page.get_by_text("Practice feedback on your last answer")).to_have_count(0)

    expect(page.get_by_role("heading", name="Interview complete. Nice work!")).to_be_visible()
    expect(page.get_by_text("You answered 6 questions and 1 follow-up.")).to_be_visible()
    expect(page.get_by_text("Q2 · Follow-up", exact=True)).to_be_visible()
    no_horizontal_scroll(page)
    page.screenshot(path=str(SHOTS / f"{tag}-3-complete.png"), full_page=True)
    page.context.close()


def no_token(browser) -> None:
    page = new_page(browser, viewport={"width": 390, "height": 844}, token=False)
    page.route("**/api/v1/**", lambda r: _json(r, 404, _err("session_not_found", "Not found.")))
    page.goto(f"{BASE}/session/{SID}/interview")
    expect(page.get_by_text("This session belongs to another browser", exact=False)).to_be_visible()
    page.screenshot(path=str(SHOTS / "no-token.png"))
    page.context.close()


def main() -> int:
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for name, fn in [
            ("desktop: start, 6 questions + follow-up, reload, 503, 429, wrong_question",
             desktop_flow),
            ("mobile 390x844 light", lambda b: mobile_flow(b, dark=False)),
            ("mobile 390x844 dark + reduced motion", lambda b: mobile_flow(b, dark=True)),
            ("no token on this device", no_token),
        ]:
            fn(browser)
            print(f"PASS  {name}")
        browser.close()
    print(f"expected non-2xx fetch logs: {len(expected_http_errors)}")
    if console_errors:
        print("FAIL  console errors:", *console_errors, sep="\n  ")
        return 1
    print(f"PASS  no console errors ({time.time() - t0:.1f}s); screenshots in {SHOTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
