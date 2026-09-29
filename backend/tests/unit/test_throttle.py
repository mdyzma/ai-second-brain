from ai_second_brain.auth.throttle import LoginThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_until_limit_then_locks() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=5, lockout_seconds=60, clock=clock)
    for _ in range(4):
        throttle.record_failure()
        assert throttle.retry_after() is None
    throttle.record_failure()
    assert throttle.retry_after() == 60


def test_retry_after_counts_down_and_rounds_up() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=1, lockout_seconds=60, clock=clock)
    throttle.record_failure()
    clock.now += 59.2
    assert throttle.retry_after() == 1


def test_lock_expires_and_counter_resets() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=2, lockout_seconds=60, clock=clock)
    throttle.record_failure()
    throttle.record_failure()
    clock.now += 60
    assert throttle.retry_after() is None
    throttle.record_failure()
    assert throttle.retry_after() is None  # one failure after reset is below the limit


def test_success_resets() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=2, lockout_seconds=60, clock=clock)
    throttle.record_failure()
    throttle.record_success()
    throttle.record_failure()
    assert throttle.retry_after() is None
