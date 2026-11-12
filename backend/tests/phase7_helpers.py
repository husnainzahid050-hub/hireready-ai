"""Shared helpers for the Phase 7 tests: env-driven settings, a recording email provider, and a
ready report with a 7-day plan."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.core.config import Settings, get_settings
from app.schemas.analysis import PrepDay
from app.schemas.report import EmployerView, Readiness, Report
from app.services.email import EmailError

SECRETS = {
    "CRON_SECRET": "cron-test-secret",
    "REMINDER_TOKEN_SECRET": "reminder-test-secret",
    "RESEND_API_KEY": "re_test",
    "EMAIL_FROM": "HireReady <reports@example.com>",
    "APP_BASE_URL": "https://hireready.example",
}


@contextmanager
def env(monkeypatch: pytest.MonkeyPatch, **values: str) -> Iterator[Settings]:
    """Set env vars and rebuild the cached settings for the duration of the block."""
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        for k in values:
            monkeypatch.delenv(k, raising=False)
        get_settings.cache_clear()


class RecordingEmail:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send(self, **kw: Any) -> None:
        if self.fail:
            raise EmailError("down")
        self.sent.append(kw)


def plan(n: int = 7) -> list[PrepDay]:
    return [
        PrepDay(
            day=i + 1,
            focus=f"Focus {i + 1}",
            tasks=[f"Task {i + 1}a", f"Task {i + 1}b", "Task extra (dropped)"],
            resource_urls=["https://not-allowlisted.example/x"],
        )
        for i in range(n)
    ]


def report(days: int = 7) -> Report:
    return Report(
        generated_at="2026-11-12T10:00:00+00:00",
        generated_by="llm",
        role_title="Junior AI Engineer",
        readiness=Readiness(
            score=68,
            band="getting_there",
            band_label="Getting there",
            interview_score=66,
            match_score=72,
            formula="0.7 x 66 + 0.3 x 72",
            weights={"interview": 0.7, "match": 0.3},
        ),
        employer=EmployerView(
            verdict="lean_yes",
            verdict_label="Lean yes",
            score_verdict="lean_yes",
            reaction="r",
            green_flags=[],
            red_flags=[],
        ),
        questions=[],
        speech=None,
        strengths=[],
        improvements=[],
        open_gaps=[],
        prep_plan=plan(days),
    )
