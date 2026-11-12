"""Real-browser test of the analysis page's edge states against a mocked API (no backend).

Covers: a second tab that waits for a run already in progress, a stream that closes without
`done`/`error` (proxy or platform timeout), the time-budget error after a "slow" notice, and a
wrong or expired session token.

Usage (with the production build running):
    npm run build && npx next start -p 3001
    python e2e/analysis.mock.py          (E2E_BASE=http://localhost:3004 for another port)
"""

from __future__ import annotations

import json
import os
import sys

from playwright.sync_api import Page, Route, expect, sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:3001")
SID = "11111111-2222-3333-4444-555555555555"
ANALYSIS = {
    "role_title": "Junior AI Engineer",
    "match_score": 72,
    "breakdown": {
        "formula": "100 x (0.7 x must + 0.2 x nice + 0.1 x seniority)",
        "must_have": {"weight": 0.7, "score": 0.7, "detail": "7 of 10"},
        "nice_to_have": {"weight": 0.2, "score": 0.5, "detail": "1 of 2"},
        "seniority_fit": {"weight": 0.1, "score": 1.0, "detail": "Junior"},
    },
    # Duplicate names on purpose: keys must not collide (QA B16).
    "gaps": [
        {"skill": "Python", "importance": "must_have", "competency": "python",
         "verdict": "strong_evidence", "evidence_quote": "Built X in Python", "reason": "r",
         "quote_verified": True},
        {"skill": "Python", "importance": "must_have", "competency": "python",
         "verdict": "weak_evidence", "evidence_quote": None, "reason": "r2",
         "quote_verified": False},
    ],
    "strengths": [],
    "likely_questions": [{"topic": "Python", "questions": ["Q?", "Q?"]}],
    "prep_plan": [{"day": d, "focus": "f", "tasks": ["t", "t"], "resource_urls": []}
                  for d in range(1, 8)],
}  # fmt: skip

errors: list[str] = []


def sse(*events: tuple[str, dict]) -> str:
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)


def api(stream: str, analysis_status: int = 200):
    def handle(route: Route) -> None:
        url = route.request.url
        if url.endswith("/analysis"):
            body = (
                {"session": {"id": SID}, "analysis": None}
                if analysis_status == 200
                else {"error": {"code": "session_not_found", "message": "Session not found."}}
            )
            route.fulfill(status=analysis_status, content_type="application/json",
                          body=json.dumps(body))
        elif url.endswith("/analyze"):
            route.fulfill(status=200, content_type="text/event-stream", body=stream)
        else:
            route.abort()

    return handle


def open_page(browser, handler) -> Page:
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"localStorage.setItem('hireready:token:{SID}', 'tok-123')")
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
            and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.route("**/api/v1/**", handler)
    page.goto(f"{BASE}/session/{SID}/analysis")
    return page


def second_tab_waits(browser) -> None:
    waiting = ("status", {"step": "waiting", "message": "Already running. Waiting…"})
    page = open_page(browser, api(sse(waiting, ("done", ANALYSIS))))
    expect(page.get_by_role("heading", name="Your match for Junior AI Engineer")).to_be_visible()
    expect(page.get_by_text("Strong evidence")).to_be_visible()
    expect(page.get_by_text("Start interview")).to_be_visible()
    page.context.close()


def stream_cut_short(browser) -> None:
    page = open_page(browser, api(sse(("status", {"step": "extract", "message": "Reading…"}))))
    expect(page.get_by_text("The connection closed before the analysis finished")).to_be_visible()
    expect(page.get_by_role("heading", name="Analysis stopped")).to_be_visible()
    expect(page.get_by_role("button", name="Try again")).to_be_visible()
    # Nothing keeps pulsing after the run stopped (UX_REVIEW item 4).
    expect(page.locator(".animate-pulse")).to_have_count(0)
    expect(page.get_by_text("Not available").first).to_be_visible()
    page.context.close()


def slow_then_timeout(browser) -> None:
    page = open_page(browser, api(sse(
        ("status", {"step": "match", "message": "Checking each required skill…"}),
        ("status", {"step": "slow", "message": "Taking longer than usual…"}),
        ("error", {"code": "analysis_timeout", "message": "Our AI providers are busy."}),
    )))  # fmt: skip
    expect(page.get_by_text("Our AI providers are busy.")).to_be_visible()
    # "slow" changed only the message: the progress stays on "Match skills".
    expect(page.locator("li[aria-current]")).to_have_count(1)
    expect(page.locator("li[aria-current]")).to_contain_text("Match skills")
    expect(page.locator("li[aria-current]")).to_contain_text("(stopped)")
    page.context.close()


def expired_token(browser) -> None:
    page = open_page(browser, api("", analysis_status=404))
    expect(page.get_by_text("This session belongs to another browser")).to_be_visible()
    expect(page.get_by_text("Analyzing your CV")).to_have_count(0)
    page.context.close()


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--mute-audio"])
        for name, fn in [
            ("second tab waits for the running analysis", second_tab_waits),
            ("stream closed without done shows error + retry", stream_cut_short),
            ("slow notice keeps the step, then timeout error", slow_then_timeout),
            ("wrong / expired token shows the session panel", expired_token),
        ]:
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
