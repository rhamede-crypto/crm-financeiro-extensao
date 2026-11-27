from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True, slots=True)
class ReminderDecision:
    action: str
    reason: str
    iso_year: int
    iso_week: int


def evaluate_weekly_reminder(
    *,
    enabled: bool,
    weekday: str,
    now_local: datetime,
    last_consolidated_local: datetime | None,
    already_logged_this_week: bool,
    fresh_days: int = 6,
) -> ReminderDecision:
    """Deterministically decides whether a company should receive the weekly upload reminder."""
    iso = now_local.isocalendar()
    iso_year, iso_week = int(iso.year), int(iso.week)

    if not enabled:
        return ReminderDecision("skip", "disabled", iso_year, iso_week)

    target_weekday = WEEKDAY_INDEX.get(weekday, -1)
    if now_local.weekday() != target_weekday:
        return ReminderDecision("skip", "wrong_weekday", iso_year, iso_week)

    if already_logged_this_week:
        return ReminderDecision("skip", "already_dispatched", iso_year, iso_week)

    if last_consolidated_local is not None:
        cutoff = now_local - timedelta(days=fresh_days)
        if last_consolidated_local >= cutoff:
            return ReminderDecision("skip_fresh", "skipped_up_to_date", iso_year, iso_week)

    return ReminderDecision("send", "due", iso_year, iso_week)
