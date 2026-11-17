from datetime import date

import pandas as pd
import pytest

from pipeline.errors import PermanentProviderError, TransientProviderError
from pipeline.providers.retry import Throttle, call_with_retry
from pipeline.providers.vnstock_provider import VnstockProvider, classify_error, normalize, year_windows


def test_year_windows_cover_range_without_overlap():
    ws = year_windows(date(2023, 11, 9), date(2026, 11, 9))
    assert len(ws) == 4 or len(ws) == 3 + 1
    assert ws[0][1] == date(2026, 11, 9) and ws[-1][0] == date(2023, 11, 9)
    for (s1, e1), (s2, e2) in zip(ws, ws[1:]):
        assert e2 == s1 - pd.Timedelta(days=1)
    assert all((e - s).days <= 364 for s, e in ws)


def test_normalize_units_timezone_and_dedup():
    raw = pd.DataFrame({
        "time": pd.to_datetime(["2026-11-09 00:00", "2026-11-06 00:00", "2026-11-06 00:00"]).tz_localize("Asia/Ho_Chi_Minh"),
        "open": [53.6, 51.0, 51.0], "high": [54.0, 52.0, 52.0], "low": [53.0, 50.0, 50.0],
        "close": [53.6, 51.0, 51.0], "volume": [10, 20, 20],
    })
    out = normalize(raw, "vcb")
    assert list(out.trade_date) == [date(2026, 11, 6), date(2026, 11, 9)]  # không lệch ngày sang UTC
    assert out.close.tolist() == [51000.0, 53600.0]  # nghìn VND -> VND, không rơi float
    assert out.symbol.unique().tolist() == ["VCB"]


def test_classify_error():
    class EntitlementError(Exception): ...
    e = classify_error(EntitlementError("Đã dùng hết hạn mức theo phút"))
    assert isinstance(e, TransientProviderError) and e.rate_limited
    assert isinstance(classify_error(ValueError("Symbol not found")), PermanentProviderError)
    assert isinstance(classify_error(ConnectionError("boom")), TransientProviderError)


def test_retry_waits_for_minute_on_rate_limit_then_backoff():
    sleeps, calls = [], iter([TransientProviderError("x", rate_limited=True), TransientProviderError("y"), "ok"])

    def fn():
        v = next(calls)
        if isinstance(v, Exception):
            raise v
        return v

    assert call_with_retry(fn, sleep=sleeps.append) == "ok"
    assert sleeps == [65.0, 4.0]


def test_retry_gives_up_and_permanent_not_retried():
    with pytest.raises(TransientProviderError):
        call_with_retry(lambda: (_ for _ in ()).throw(TransientProviderError("x")), attempts=2, sleep=lambda s: None)
    n = []
    def perm():
        n.append(1); raise PermanentProviderError("no")
    with pytest.raises(PermanentProviderError):
        call_with_retry(perm, sleep=lambda s: None)
    assert len(n) == 1


def test_throttle_spaces_calls():
    t, slept = [0.0], []
    th = Throttle(8, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    th.wait(); th.wait()
    assert slept == [pytest.approx(7.5)]


def test_provider_stitches_windows_and_window_failure_fails_symbol():
    def fetcher(sym, s, e):
        return pd.DataFrame({"time": pd.to_datetime([e.isoformat()]), "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [5]})

    p = VnstockProvider(window_fetcher=fetcher, sleep=lambda s: None, throttle=Throttle(1e9, sleep=lambda s: None))
    res = p.fetch("FPT", date(2023, 11, 9), date(2026, 11, 9))
    assert len(res.prices) == len(year_windows(date(2023, 11, 9), date(2026, 11, 9)))
    assert res.prices.trade_date.is_monotonic_increasing

    def bad(sym, s, e):
        raise PermanentProviderError("no such symbol")
    with pytest.raises(PermanentProviderError):
        VnstockProvider(window_fetcher=bad, sleep=lambda s: None, throttle=Throttle(1e9)).fetch("X", date(2025, 1, 1), date(2026, 1, 1))
