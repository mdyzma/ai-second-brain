from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from ai_second_brain.nightly.schedule import parse_hhmm, run_date_for, should_start

WAW = ZoneInfo("Europe/Warsaw")


def utc(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def start(now: datetime, at: str = "02:00", *, enabled: bool = True, done: bool = False) -> bool:
    return should_start(now, WAW, parse_hhmm(at), enabled=enabled, has_scheduled_run_today=done)


@pytest.mark.parametrize(
    ("text", "expected"), [("02:00", time(2, 0)), ("00:00", time(0, 0)), ("23:45", time(23, 45))]
)
def test_parse_hhmm(text: str, expected: time) -> None:
    assert parse_hhmm(text) == expected


@pytest.mark.parametrize("text", ["2:00", "24:00", "12:60", "", "0200", "02:00:00", "ab:cd"])
def test_parse_hhmm_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_hhmm(text)


def test_before_and_after_the_local_time() -> None:
    # 2026-10-04 is CEST (UTC+2): 02:00 local = 00:00 UTC.
    assert not start(utc(2026, 10, 3, 23, 45))  # 01:45 local
    assert start(utc(2026, 10, 4, 0, 0))  # 02:00 local
    assert start(utc(2026, 10, 4, 7, 0))  # 09:00 local: catch-up after a missed 02:00


def test_disabled_or_already_ran() -> None:
    assert not start(utc(2026, 10, 4, 7), enabled=False)
    assert not start(utc(2026, 10, 4, 7), done=True)


def test_spring_forward_gap() -> None:
    # 2026-03-29 Europe/Warsaw: 02:00 -> 03:00. "02:30" does not exist that day.
    assert not start(utc(2026, 3, 29, 0, 45), "02:30")  # 01:45 CET
    assert start(utc(2026, 3, 29, 1, 0), "02:30")  # 03:00 CEST, first tick after the gap


def test_fall_back_repeats_the_hour_once() -> None:
    # 2026-10-25: 03:00 CEST -> 02:00 CET. 02:30 happens twice; one run per date.
    assert start(utc(2026, 10, 25, 0, 30), "02:30")  # first 02:30 (CEST)
    assert not start(utc(2026, 10, 25, 1, 30), "02:30", done=True)  # second 02:30 (CET)


def test_midnight_and_late_times() -> None:
    assert start(utc(2026, 10, 3, 22, 0), "00:00")  # 00:00 local on 10-04
    assert not start(utc(2026, 10, 4, 21, 30), "23:45")  # 23:30 local
    assert start(utc(2026, 10, 4, 21, 45), "23:45")


def test_run_date_is_the_local_date() -> None:
    assert run_date_for(utc(2026, 10, 3, 22, 30), WAW) == date(2026, 10, 4)
    assert run_date_for(utc(2026, 10, 3, 21, 30), WAW) == date(2026, 10, 3)
