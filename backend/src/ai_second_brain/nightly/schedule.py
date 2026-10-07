"""When the nightly run starts. Pure functions of the clock; no I/O.

procrastinate evaluates cron in UTC and drops ticks more than 10 minutes late, so the
periodic task only ticks; the local-time decision lives here (spec §5.1).
"""

import re
from datetime import date, datetime, time, tzinfo
from zoneinfo import ZoneInfo

import tzlocal

_HHMM = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")


def parse_hhmm(text: str) -> time:
    match = _HHMM.fullmatch(text)
    if not match:
        raise ValueError("expected HH:MM between 00:00 and 23:59")
    return time(int(match[1]), int(match[2]))


def resolve_zone(name: str) -> tzinfo:
    """An IANA zone, or the host's local zone when empty. Raises on unknown names."""
    if not name:
        # The host's real IANA zone, not a fixed UTC offset: an offset would not follow DST,
        # so the default (empty) setting would shift the nightly start by an hour after a
        # clock change (spec exit criterion 1).
        return tzlocal.get_localzone()
    return ZoneInfo(name)


def run_date_for(now_utc: datetime, tz: tzinfo) -> date:
    return now_utc.astimezone(tz).date()


def should_start(
    now_utc: datetime,
    tz: tzinfo,
    nightly_at: time,
    *,
    enabled: bool,
    has_scheduled_run_today: bool,
) -> bool:
    """True once the local wall clock has reached `nightly_at` today and no run has started.

    Comparing wall-clock times makes DST safe: a nonexistent 02:30 is first reached at 03:00,
    and a repeated 02:30 is blocked by `has_scheduled_run_today`.
    """
    if not enabled or has_scheduled_run_today:
        return False
    return now_utc.astimezone(tz).time() >= nightly_at
