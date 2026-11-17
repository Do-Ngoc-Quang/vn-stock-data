from datetime import date

import pytest

from pipeline.config import Config
from pipeline.errors import PermanentProviderError, TransientProviderError
from pipeline.providers import registry
from pipeline.providers.cafef_provider import CafefProvider, normalize


def row(ngay, o, h, l, c, adj, vol):
    return {"Symbol": "FPT", "Ngay": ngay, "GiaMoCua": o, "GiaCaoNhat": h, "GiaThapNhat": l,
            "GiaDongCua": c, "GiaDieuChinh": adj, "KhoiLuongKhopLenh": vol, "KLThoaThuan": 0}


def make_fetcher(rows, total=None, log=None):
    def fetch(symbol, start, end, page, exchange="HOSE"):
        if log is not None:
            log.append((start, end, page))
        chunk = rows[(page - 1) * 30: page * 30]
        return {"Data": {"TotalCount": len(rows) if total is None else total, "Data": chunk}}
    return fetch


def provider(fetcher):
    return CafefProvider(page_fetcher=fetcher, sleep=lambda s: None, throttle=type("T", (), {"wait": lambda self: None})())


def test_normalize_applies_adjust_ratio_units_and_date():
    import pandas as pd
    raw = pd.DataFrame([row("04/01/2022", 93.4, 94.2, 93.3, 93.5, 46.75, 1935000),
                        row("30/12/2022", 76.2, 76.9, 76.0, 76.9, 76.9, 628600)])
    out = normalize(raw, "fpt")
    assert out.trade_date.tolist() == [date(2022, 1, 4), date(2022, 12, 30)]
    assert out.close.tolist() == [46750.0, 76900.0]       # nhân hệ số 0,5 rồi đổi nghìn VND -> VND
    assert out.open.tolist() == [46700.0, 76200.0]
    assert out.volume.tolist() == [1935000, 628600]
    assert (out.low <= out.close).all() and (out.close <= out.high).all()


def test_normalize_zero_close_is_kept_for_validation_not_divided():
    import pandas as pd
    out = normalize(pd.DataFrame([row("02/01/2023", 0, 0, 0, 0, 0, 5)]), "fpt")
    assert out.close.tolist() == [0.0]


def test_fetch_paginates_each_window_and_merges_without_duplicates():
    rows = [row(f"{d:02d}/06/2026", 10, 11, 9, 10, 10, 1) for d in range(28, 0, -1)] * 2  # 56 dòng, 28 ngày trùng
    log = []
    res = provider(make_fetcher(rows, log=log)).fetch("FPT", date(2026, 1, 1), date(2026, 6, 30))
    assert [p for *_, p in log] == [1, 2]                 # 56 dòng / 30 = 2 trang
    assert len(res.raw) == 56 and len(res.prices) == 28
    assert res.prices.trade_date.is_monotonic_increasing


def test_fetch_uses_year_windows():
    log = []
    provider(make_fetcher([], log=log)).fetch("FPT", date(2023, 11, 9), date(2026, 11, 9))
    assert len({(s, e) for s, e, _ in log}) == 4          # 4 cửa sổ <= 365 ngày


def test_empty_symbol_returns_empty_prices():
    res = provider(make_fetcher([])).fetch("ZZZ", date(2026, 1, 1), date(2026, 3, 1))
    assert len(res.prices) == 0


def test_malformed_response_is_permanent():
    with pytest.raises(PermanentProviderError):
        provider(lambda *a: {"oops": 1}).fetch("FPT", date(2026, 1, 1), date(2026, 3, 1))


def test_transient_error_is_retried():
    calls = []
    def flaky(symbol, start, end, page, exchange):
        calls.append(1)
        if len(calls) == 1:
            raise TransientProviderError("HTTP 503")
        return {"Data": {"TotalCount": 0, "Data": []}}
    provider(flaky).fetch("FPT", date(2026, 1, 1), date(2026, 3, 1))
    assert len(calls) == 4  # 1 lần lỗi + thử lại, rồi dò tiếp HNX và UPCOM vì HOSE rỗng


def test_registry_builds_cafef():
    p = registry.create_provider(Config(provider="cafef"))
    assert isinstance(p, CafefProvider) and p.source == "cafef"


def test_exchange_is_probed_then_reused():
    calls = []
    def fetch(symbol, start, end, page, exchange):
        calls.append(exchange)
        data = [row("17/11/2026", 10, 11, 9, 10, 10, 1)] if exchange == "UPCOM" else []
        return {"Data": {"TotalCount": len(data), "Data": data}}
    res = provider(fetch).fetch("ACV", date(2023, 11, 9), date(2026, 11, 9))  # 4 cửa sổ
    assert calls[:3] == ["HOSE", "HNX", "UPCOM"] and set(calls[3:]) == {"UPCOM"}
    assert len(res.prices) == 1
