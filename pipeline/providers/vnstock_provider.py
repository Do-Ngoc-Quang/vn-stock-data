"""Adapter vnstock duy nhất (thiết kế mục 4.4). Mọi lời gọi vnstock nằm trong tệp này."""
from __future__ import annotations

from datetime import date, timedelta
from importlib import metadata
from typing import Callable

import pandas as pd

from pipeline.errors import PermanentProviderError, TransientProviderError
from pipeline.providers.base import STANDARD_COLUMNS, FetchResult
from pipeline.providers.retry import Throttle, call_with_retry

VN_TZ = "Asia/Ho_Chi_Minh"
PRICE_FACTOR = 1000  # vnstock 5.2.2 trả giá theo nghìn VND (đã xác nhận ở probe)
WINDOW_DAYS = 365    # mỗi lần gọi chỉ trả tối đa ~1 năm (D11)
_PERMANENT_HINTS = ("not found", "không tồn tại", "khong ton tai", "invalid symbol", "unknown symbol")


def year_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Chia [start, end] thành các cửa sổ không chồng lấn dài tối đa 1 năm, từ mới đến cũ."""
    windows: list[tuple[date, date]] = []
    w_end = end
    while w_end >= start:
        w_start = max(start, w_end - timedelta(days=WINDOW_DAYS - 1))
        windows.append((w_start, w_end))
        w_end = w_start - timedelta(days=1)
    return windows


def classify_error(exc: Exception) -> Exception:
    name, msg = type(exc).__name__, str(exc)
    low = msg.lower()
    if name == "EntitlementError" or "hạn mức" in low or "rate limit" in low:
        return TransientProviderError(f"{name}: {msg}", rate_limited=True)
    if any(h in low for h in _PERMANENT_HINTS):
        return PermanentProviderError(f"{name}: {msg}")
    return TransientProviderError(f"{name}: {msg}")


def normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Đổi cột `time` thành `trade_date` (ngày giờ Việt Nam, không quy đổi UTC), giá nghìn VND -> VND."""
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    df = raw.copy()
    times = pd.to_datetime(df["time"])
    if times.dt.tz is not None:
        times = times.dt.tz_convert(VN_TZ)
    out = pd.DataFrame({
        "symbol": symbol.upper(),
        "trade_date": times.dt.date,
    })
    for col in ("open", "high", "low", "close"):
        out[col] = (df[col].astype("float64") * PRICE_FACTOR).round(2).to_numpy()
    out["volume"] = df["volume"].fillna(0).astype("int64").to_numpy()
    out = out.drop_duplicates(subset="trade_date", keep="last").sort_values("trade_date")
    return out[STANDARD_COLUMNS].reset_index(drop=True)


class VnstockProvider:
    name = "vnstock"

    def __init__(
        self,
        source: str = "vci",
        calls_per_minute: float = 8,
        retry_attempts: int = 4,
        window_fetcher: Callable[[str, date, date], pd.DataFrame] | None = None,
        sleep=None,
        throttle: Throttle | None = None,
    ):
        import time

        self.source = source
        self._sleep = sleep or time.sleep
        self._throttle = throttle or Throttle(calls_per_minute, sleep=self._sleep)
        self._attempts = retry_attempts
        self._fetch_window = window_fetcher or self._vnstock_window

    @property
    def version(self) -> str:
        try:
            return metadata.version("vnstock")
        except metadata.PackageNotFoundError:
            return "unknown"

    def _vnstock_window(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        from vnstock import Market  # nhập muộn để test không cần cài vnstock

        return Market().equity(symbol).ohlcv(
            start=start.isoformat(), end=end.isoformat(), interval="1D", source=self.source
        )

    def _one_window(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        def call():
            self._throttle.wait()
            try:
                return self._fetch_window(symbol, start, end)
            except (TransientProviderError, PermanentProviderError):
                raise
            except Exception as exc:  # noqa: BLE001 - phân loại mọi lỗi từ vnstock
                raise classify_error(exc) from exc

        return call_with_retry(call, attempts=self._attempts, sleep=self._sleep)

    def fetch(self, symbol: str, start: date, end: date) -> FetchResult:
        frames = []
        for w_start, w_end in year_windows(start, end):
            df = self._one_window(symbol, w_start, w_end)  # một cửa sổ lỗi = cả mã lỗi
            if df is not None and len(df):
                frames.append(df)
        if not frames:
            empty = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
            return FetchResult(raw=empty, prices=normalize(empty, symbol))
        raw = pd.concat(frames, ignore_index=True)
        return FetchResult(raw=raw, prices=normalize(raw, symbol))
