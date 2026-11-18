"""Kiểm tra chất lượng (thiết kế mục 5)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from pipeline.config import Config


@dataclass(frozen=True)
class Issue:
    symbol: str | None
    check_code: str
    severity: str  # 'error' | 'warn'
    detail: str


def widen_range_to_close(df: pd.DataFrame) -> pd.DataFrame:
    """Dòng có close lệch nhẹ ngoài [low, high] (đã cảnh báo CLOSE_NEAR_RANGE): nới high/low để bao lấy close,
    giữ ràng buộc `close BETWEEN low AND high` của schema. Chỉ gọi cho mã đã qua kiểm tra."""
    out = df.copy()
    out["high"] = out[["high", "close"]].max(axis=1)
    out["low"] = out[["low", "close"]].min(axis=1)
    return out


def validate_symbol(symbol: str, df: pd.DataFrame, cfg: Config, exchange: str | None = None) -> list[Issue]:
    """Kiểm tra theo mã. Có ít nhất một issue `error` thì mã bị loại."""
    if df is None or len(df) == 0:
        return [Issue(symbol, "EMPTY", "error", "không có dòng nào")]

    issues: list[Issue] = []

    def add(code: str, sev: str, detail: str):
        issues.append(Issue(symbol, code, sev, detail))

    dup = df["trade_date"].duplicated(keep=False)
    if dup.any():
        add("DUPLICATE_DATE", "error", f"{int(dup.sum())} dòng trùng ngày, ví dụ {df.loc[dup, 'trade_date'].iloc[0]}")

    prices = df[["open", "high", "low", "close"]]
    bad = (prices <= 0).any(axis=1) | prices.isna().any(axis=1)
    if bad.any():
        add("NON_POSITIVE_PRICE", "error", f"{int(bad.sum())} dòng có giá <= 0 hoặc thiếu, đầu tiên {df.loc[bad, 'trade_date'].iloc[0]}")

    m = df["high"] < df["low"]
    if m.any():
        add("HIGH_LT_LOW", "error", f"{int(m.sum())} dòng có high < low, đầu tiên {df.loc[m, 'trade_date'].iloc[0]}")

    m = (df["close"] < df["low"]) | (df["close"] > df["high"])
    if m.any():
        # độ lệch của close so với đầu mút gần nhất của [low, high], theo %
        dev = pd.concat([(df["low"] - df["close"]) / df["low"], (df["close"] - df["high"]) / df["high"]], axis=1).max(axis=1) * 100
        far = m & (dev > cfg.close_range_tolerance_pct)
        near = m & ~far
        if far.any():
            add("CLOSE_OUT_OF_RANGE", "error", f"{int(far.sum())} dòng có close ngoài [low, high] quá {cfg.close_range_tolerance_pct:g}%, đầu tiên {df.loc[far, 'trade_date'].iloc[0]}")
        if near.any():
            add("CLOSE_NEAR_RANGE", "warn", f"{int(near.sum())} dòng có close lệch [low, high] ≤ {cfg.close_range_tolerance_pct:g}%, đầu tiên {df.loc[near, 'trade_date'].iloc[0]}")

    m = df["volume"] < 0
    if m.any():
        add("NEGATIVE_VOLUME", "error", f"{int(m.sum())} dòng có volume < 0, đầu tiên {df.loc[m, 'trade_date'].iloc[0]}")

    ordered = df.sort_values("trade_date").reset_index(drop=True)
    pct = ordered["close"].pct_change().abs() * 100
    thr = cfg.move_threshold(exchange)
    m = pct > thr
    if m.any():
        first = ordered.loc[m, "trade_date"].iloc[0]
        add("LARGE_DAILY_MOVE", "warn", f"{int(m.sum())} phiên biến động > {thr:g}%, lớn nhất {pct.max():.1f}%, đầu tiên {first}")

    zero = float((df["volume"] == 0).mean())
    if zero > cfg.zero_volume_ratio:
        add("ZERO_VOLUME_DAYS", "warn", f"{zero:.0%} phiên có volume = 0")

    if len(df) < cfg.short_history_rows:
        add("SHORT_HISTORY", "warn", f"{len(df)} phiên < {cfg.short_history_rows} cần cho SMA200")

    return issues


def has_error(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def check_stale(as_of: date | None, run_date: date, cfg: Config) -> Issue | None:
    if as_of is None:
        return None
    gap = (run_date - as_of).days
    if gap > cfg.stale_days:
        return Issue(None, "STALE_DATA", "warn", f"phiên mới nhất {as_of} cách ngày chạy {gap} ngày > {cfg.stale_days}")
    return None


def check_coverage(total: int, excluded: int, failed: int, cfg: Config) -> Issue | None:
    bad = excluded + failed
    if total and bad / total > cfg.failure_threshold:
        return Issue(None, "UNIVERSE_COVERAGE", "error",
                     f"{bad}/{total} mã bị loại hoặc lỗi ({bad / total:.0%}) > {cfg.failure_threshold:.0%}")
    return None
