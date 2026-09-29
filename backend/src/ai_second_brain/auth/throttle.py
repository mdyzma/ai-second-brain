"""In-process login throttle.

State lives in this process only. That is acceptable because the API is single-user and
single-process (spec §6.1). After ``max_failures`` consecutive failures, logins are refused
for ``lockout_seconds``. A success resets the counter.
"""

import math
import time
from collections.abc import Callable


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = 5,
        lockout_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures = 0
        self._locked_until: float | None = None

    def retry_after(self) -> int | None:
        """Whole seconds until the next attempt is allowed, or None when not locked."""
        if self._locked_until is None:
            return None
        remaining = self._locked_until - self._clock()
        if remaining <= 0:
            self._locked_until = None
            self._failures = 0
            return None
        return max(1, math.ceil(remaining))

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._max_failures:
            self._locked_until = self._clock() + self._lockout_seconds

    def record_success(self) -> None:
        self._failures = 0
        self._locked_until = None
