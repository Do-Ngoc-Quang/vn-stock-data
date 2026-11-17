import math

import pandas as pd
import pytest

from pipeline.features.indicators import compute_features
from tests.helpers import make_prices


def naive(df):
    c, h, l, v = list(df.close), list(df.high), list(df.low), list(df.volume)
    n = len(c)
    nan = float("nan")

    def sma(x, k):
        return [nan if i + 1 < k else sum(x[i + 1 - k:i + 1]) / k for i in range(n)]

    def ema(x, k):
        out, a = [nan] * n, 2 / (k + 1)
        e = None
        for i in range(n):
            if math.isnan(x[i]):
                continue
            e = x[i] if e is None else a * x[i] + (1 - a) * e
            out[i] = e
        first = next(i for i in range(n) if not math.isnan(x[i]))
        return [nan if i < first + k - 1 else out[i] for i in range(n)]

    res = {"sma20": sma(c, 20), "sma50": sma(c, 50), "sma200": sma(c, 200), "ema12": ema(c, 12), "ema26": ema(c, 26)}
    # RSI Wilder
    rsi = [nan] * n
    ag = al = None
    for i in range(1, n):
        d = c[i] - c[i - 1]
        g, ls = max(d, 0), max(-d, 0)
        # dạng đệ quy ewm(alpha=1/14, adjust=False) khởi tạo bằng giá trị đầu
        ag = g if i == 1 else ag + (g - ag) / 14
        al = ls if i == 1 else al + (ls - al) / 14
        if i >= 14:
            rsi[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    res["rsi14"] = rsi
    macd = [a - b if not (math.isnan(a) or math.isnan(b)) else nan for a, b in zip(res["ema12"], res["ema26"])]
    sig = ema(macd, 9)
    res["macd"], res["macd_signal"] = macd, sig
    res["macd_hist"] = [m - s if not (math.isnan(m) or math.isnan(s)) else nan for m, s in zip(macd, sig)]
    mid = sma(c, 20)
    sd = [nan if i < 19 else (sum((x - mid[i]) ** 2 for x in c[i - 19:i + 1]) / 20) ** 0.5 for i in range(n)]
    res["bb_mid"] = mid
    res["bb_upper"] = [m + 2 * s for m, s in zip(mid, sd)]
    res["bb_lower"] = [m - 2 * s for m, s in zip(mid, sd)]
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
    atr, a = [nan] * n, tr[0]
    for i in range(n):
        a = tr[0] if i == 0 else a + (tr[i] - a) / 14
        if i >= 13:
            atr[i] = a
    res["atr14"] = atr
    res["vol_sma20"] = sma([float(x) for x in v], 20)
    return res


@pytest.mark.parametrize("n", [260, 40])
def test_matches_independent_computation(n):
    df = make_prices("AAA", n=n)
    got = compute_features(df)
    exp = naive(df)
    for col, vals in exp.items():
        for g, e in zip(got[col], vals):
            if e != e:
                assert pd.isna(g), col
            else:
                assert g == pytest.approx(e, rel=1e-9, abs=1e-9), col


def test_null_until_enough_sessions_and_no_zero_fill():
    got = compute_features(make_prices("AAA", n=60))
    assert got["sma200"].isna().all()
    assert got["sma20"].iloc[:19].isna().all() and pd.notna(got["sma20"].iloc[19])
    assert got["macd_signal"].iloc[:33].isna().all() and pd.notna(got["macd_signal"].iloc[33])


def test_rsi_all_gains_is_100():
    df = make_prices("AAA", n=30)
    df["close"] = [1000.0 + i for i in range(30)]
    df["high"] = df["close"] + 1
    df["low"] = df["close"] - 1
    assert compute_features(df)["rsi14"].iloc[-1] == 100.0
