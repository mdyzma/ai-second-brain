from ai_second_brain.eval.embedding import BatchProgress, format_eta, progress_line


def test_eta_formats_minutes_and_hours() -> None:
    assert format_eta(0) == "00:00"
    assert format_eta(65.4) == "01:05"
    assert format_eta(3599) == "59:59"
    assert format_eta(3600) == "1:00:00"
    assert format_eta(14 * 3600 + 2 * 60 + 3) == "14:02:03"


def test_no_eta_before_three_batches() -> None:
    line = progress_line(BatchProgress("bge-m3:567m", 64, 960, batches=2, seconds=4.0))
    assert line == "bge-m3:567m 64/960 chunks · 16.0/s · ETA …"


def test_eta_from_this_runs_rate_after_three_batches() -> None:
    # 96 chunks in 6 s → 16/s; 864 left → 54 s
    line = progress_line(BatchProgress("bge-m3:567m", 96, 960, batches=3, seconds=6.0))
    assert line == "bge-m3:567m 96/960 chunks · 16.0/s · ETA 00:54"


def test_long_eta_uses_hours() -> None:
    line = progress_line(BatchProgress("m", 100, 100_100, batches=10, seconds=50.0))
    assert line == "m 100/100100 chunks · 2.0/s · ETA 13:53:20"


def test_zero_elapsed_does_not_divide_by_zero() -> None:
    line = progress_line(BatchProgress("m", 32, 64, batches=3, seconds=0.0))
    assert line == "m 32/64 chunks · 0.0/s · ETA …"
