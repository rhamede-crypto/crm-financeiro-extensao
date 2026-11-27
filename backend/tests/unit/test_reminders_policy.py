from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.services.reminders import evaluate_weekly_reminder


def test_weekly_reminder_policy_respects_weekday_freshness_and_dedup() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    monday = datetime(2026, 10, 26, 9, 0, tzinfo=tz)  # ISO week 44, Monday

    assert (
        evaluate_weekly_reminder(
            enabled=False,
            weekday="monday",
            now_local=monday,
            last_consolidated_local=None,
            already_logged_this_week=False,
        ).action
        == "skip"
    )
    assert (
        evaluate_weekly_reminder(
            enabled=True,
            weekday="friday",
            now_local=monday,
            last_consolidated_local=None,
            already_logged_this_week=False,
        ).action
        == "skip"
    )
    assert (
        evaluate_weekly_reminder(
            enabled=True,
            weekday="monday",
            now_local=monday,
            last_consolidated_local=None,
            already_logged_this_week=True,
        ).action
        == "skip"
    )
    fresh = evaluate_weekly_reminder(
        enabled=True,
        weekday="monday",
        now_local=monday,
        last_consolidated_local=datetime(2026, 10, 23, 15, 0, tzinfo=tz),
        already_logged_this_week=False,
    )
    assert fresh.action == "skip_fresh"
    assert fresh.reason == "skipped_up_to_date"

    due = evaluate_weekly_reminder(
        enabled=True,
        weekday="monday",
        now_local=monday,
        last_consolidated_local=datetime(2026, 10, 15, 10, 0, tzinfo=tz),
        already_logged_this_week=False,
    )
    assert due.action == "send"
    assert (due.iso_year, due.iso_week) == (2026, 44)
