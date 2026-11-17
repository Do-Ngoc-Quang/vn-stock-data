"""Tính chỉ báo (thiết kế mục 6.4). Null khi chưa đủ phiên, không điền 0.

Quy ước (feature_version 1):
- SMA/vol_sma: trung bình đơn giản, cần đủ N phiên.
- EMA(N): ewm(span=N, adjust=False), bắt đầu có giá trị từ phiên thứ N.
- RSI14: làm trơn Wilder (alpha = 1/14) trên mức tăng/giảm; avg_loss = 0 -> RSI 100.
- MACD = EMA12 - EMA26; signal = EMA9 của MACD; hist = MACD - signal.
- Bollinger: SMA20 +- 2 độ lệch chuẩn tổng thể (ddof=0).
- ATR14: làm trơn Wilder trên True Range (phiên đầu: high - low).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "1"
FEATURE_COLUMNS = [
    "sma20", "sma50", "sma200", "ema12", "ema26", "rsi14",
    "macd", "macd_signal", "macd_hist", "bb_upper", "bb_mid", "bb_lower",
    "atr14", "vol_sma20",
]


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def compute_features(prices: pd.DataFrame) -> pd.DataFrame:
    """prices: một mã, cột trade_date, open, high, low, close, volume. Trả về trade_date + FEATURE_COLUMNS."""
    df = prices.sort_values("trade_date").reset_index(drop=True)
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"].astype("float64")
    out = pd.DataFrame({"trade_date": df["trade_date"]})

    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["ema12"] = _ema(close, 12)
    out["ema26"] = _ema(close, 26)

    delta = close.diff()
    gain = delta.clip(lower=0).where(delta.notna())
    loss = (-delta.clip(upper=0)).where(delta.notna())
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(~((avg_loss == 0) & avg_gain.notna()), 100.0)
    out["rsi14"] = rsi

    macd = out["ema12"] - out["ema26"]
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    out["macd"], out["macd_signal"], out["macd_hist"] = macd, signal, macd - signal

    mid = out["sma20"]
    std = close.rolling(20).std(ddof=0)
    out["bb_mid"], out["bb_upper"], out["bb_lower"] = mid, mid + 2 * std, mid - 2 * std

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1, skipna=True)
    out["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["vol_sma20"] = vol.rolling(20).mean()

    out[FEATURE_COLUMNS] = out[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    return out[["trade_date"] + FEATURE_COLUMNS]
