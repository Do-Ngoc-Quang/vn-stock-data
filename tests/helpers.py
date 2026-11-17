from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from pipeline.providers.base import STANDARD_COLUMNS, FetchResult


def make_prices(symbol: str, n: int = 260, end: date = date(2026, 11, 6), seed: int = 1, base: float = 50000.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    close = base * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    close = np.round(close, 0)
    high = np.round(close * (1 + rng.uniform(0, 0.015, n)), 0)
    low = np.round(close * (1 - rng.uniform(0, 0.015, n)), 0)
    open_ = np.round((high + low) / 2, 0)
    vol = rng.integers(100_000, 2_000_000, n)
    return pd.DataFrame({"symbol": symbol, "trade_date": days, "open": open_, "high": high, "low": low, "close": close, "volume": vol})[STANDARD_COLUMNS]


class FakeProvider:
    name, source, version = "fake", "fake", "0.0"

    def __init__(self, data: dict[str, pd.DataFrame], errors: dict | None = None):
        self.data, self.errors, self.calls = data, errors or {}, []

    def fetch(self, symbol, start, end):
        self.calls.append(symbol)
        if symbol in self.errors:
            raise self.errors[symbol]
        df = self.data[symbol]
        raw = df.rename(columns={"trade_date": "time"})[["time", "open", "high", "low", "close", "volume"]].copy()
        return FetchResult(raw=raw, prices=df.copy())


NOW = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)  # 16:00 giờ VN, sau giờ đóng cửa
