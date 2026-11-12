"""Real-browser test of the reminder link pages against a mocked API (Phase 7).

Covers: opening /reminders/[token] sends NO action (mail scanners prefetch links), the confirm
button POSTs confirm, "Mark day N done" from ?day=N, the paused state's restart button, the
/unsubscribe/[token] page (GET only checks, the button POSTs), the gone message, the private
headers on both paths, and that the Turnstile origin is NOT in the CSP of these pages.

Usage (with the production build running):
    npm run build && npx next start -p 3001
    python e2e/reminders.mock.py          (E2E_BASE=http://localhost:3004 for another port)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from playwright.sync_api import Route, expect, sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:3001")
TOKEN = "t" * 43
PLAN = [{"day": d, "focus": f"Focus {d}"} for d in range(1, 8)]
errors: list[str] = []


def status(state: str, day: int = 0, done: int = 0) -> dict:
    return {"status": state, "day": day, "days_total": 7, "last_done_day": done,
            "role_title": "Junior AI Engineer", "plan": PLAN}  # fmt: skip


def page_with(browser, initial: dict, after: dict, calls: list[str], gone: bool = False):  # type: ignore[no-untyped-def]
    ctx = browser.new_context()
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
            and errors.append(m.text))  # fmt: skip
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    def handle(route: Route) -> None:
        req = route.request
        calls.append(f"{req.method} {req.url.split('/api/v1')[1]}")
        if gone:
            route.fulfill(status=404, content_type="application/json", body=json.dumps(
                {"error": {"code": "reminder_not_found", "message": "This reminder link has expired."}}))  # fmt: skip
            return
        if "/unsubscribe/" in req.url:
            body = {"subscribed": True} if req.method == "GET" else {"unsubscribed": True}
        else:
            body = initial if req.method == "GET" else after
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/v1/**", handle)
    return ctx, page


def confirm_flow(browser) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    ctx, page = page_with(browser, status("pending"), status("active", 1), calls)
    page.goto(f"{BASE}/reminders/{TOKEN}")
    expect(page.get_by_role("heading", name="Start your 7-day plan?")).to_be_visible()
    assert calls == [f"GET /reminders/{TOKEN}"], calls  # opening the link changes nothing
    page.get_by_role("button", name="Start my 7-day plan").click()
    expect(page.get_by_role("status")).to_contain_text("Day 1 is on its way")
    expect(page.get_by_role("heading", name="Day 1 of 7")).to_be_visible()
    assert calls[-1] == f"POST /reminders/{TOKEN}/confirm", calls
    ctx.close()


def mark_done(browser) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    ctx, page = page_with(browser, status("active", 3, 2), status("active", 3, 3), calls)
    page.goto(f"{BASE}/reminders/{TOKEN}?day=3")
    page.get_by_role("button", name="Mark day 3 done").click()
    expect(page.get_by_role("status")).to_contain_text("See you tomorrow")
    assert calls[-1] == f"POST /reminders/{TOKEN}/done", calls
    expect(page.get_by_role("button", name="Mark day 3 done")).to_have_count(0)
    ctx.close()


def paused_restart(browser) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    ctx, page = page_with(browser, status("paused", 3), status("active", 3, 3), calls)
    page.goto(f"{BASE}/reminders/{TOKEN}")
    page.get_by_role("button", name="Restart my plan").click()
    expect(page.get_by_role("status")).to_contain_text("Restarted")
    assert calls[-1] == f"POST /reminders/{TOKEN}/resume", calls
    ctx.close()


def unsubscribe(browser) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    ctx, page = page_with(browser, {}, {}, calls)
    page.goto(f"{BASE}/unsubscribe/{TOKEN}")
    expect(page.get_by_role("button", name="Unsubscribe")).to_be_visible()
    assert calls == [f"GET /unsubscribe/{TOKEN}"], calls
    page.get_by_role("button", name="Unsubscribe").click()
    expect(page.get_by_role("heading", name="You're unsubscribed")).to_be_visible()
    assert calls[-1] == f"POST /unsubscribe/{TOKEN}", calls
    ctx.close()


def gone(browser) -> None:  # type: ignore[no-untyped-def]
    ctx, page = page_with(browser, {}, {}, [], gone=True)
    page.goto(f"{BASE}/reminders/{TOKEN}")
    expect(page.get_by_text("This reminder link has expired.")).to_be_visible()
    ctx.close()


def headers() -> None:
    for path in (f"/reminders/{TOKEN}", f"/unsubscribe/{TOKEN}"):
        with urllib.request.urlopen(f"{BASE}{path}") as r:  # noqa: S310 (local test server)
            h = r.headers
        assert h["X-Robots-Tag"].startswith("noindex"), path
        assert h["Referrer-Policy"] == "no-referrer", path
        assert "challenges.cloudflare.com" not in h["Content-Security-Policy"], path
    with urllib.request.urlopen(f"{BASE}/start") as r:  # noqa: S310
        assert "challenges.cloudflare.com" in r.headers["Content-Security-Policy"]


def main() -> int:
    headers()
    print("PASS  private headers; Turnstile origin only where needed")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, fn in [
            ("opening the link sends nothing; confirm button confirms", confirm_flow),
            ("mark day done from ?day=N", mark_done),
            ("paused plan restarts from the button", paused_restart),
            ("unsubscribe: GET checks, button POSTs", unsubscribe),
            ("expired link shows the gone message", gone),
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
