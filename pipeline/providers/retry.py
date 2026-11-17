"""Giữ nhịp gọi và thử lại có backoff."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from pipeline.errors import TransientProviderError

T = TypeVar("T")


class Throttle:
    """Đảm bảo tối thiểu 60/calls_per_minute giây giữa hai lần gọi."""

    def __init__(self, calls_per_minute: float, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60.0 / calls_per_minute
        self._clock, self._sleep = clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


def call_with_retry(
    fn: Callable[[], T],
    attempts: int = 4,
    sleep=time.sleep,
    rate_limit_wait: float = 65.0,
    base_backoff: float = 2.0,
) -> T:
    """Lỗi vượt hạn mức: chờ hết phút rồi thử lại. Lỗi tạm thời khác: backoff 2, 4, 8... giây."""
    last: TransientProviderError | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except TransientProviderError as exc:
            last = exc
            if attempt == attempts - 1:
                break
            sleep(rate_limit_wait if exc.rate_limited else base_backoff * (2 ** attempt))
    assert last is not None
    raise last
