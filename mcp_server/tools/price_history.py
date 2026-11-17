"""Tool get_price_history (thiết kế MCP mục 4)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from mcp_server import db
from mcp_server.errors import ToolInputError

MAX_SYMBOLS = 10
MAX_ROWS = 3000
MIN_DAYS, MAX_DAYS = 7, 365
RANGE_DAYS = {"1W": 7, "2W": 14, "1M": 30, "3M": 90, "6M": 180, "1Y": 365}
INTERVALS = ("1D", "1W")
INDICATORS = {
    "SMA20": ["sma20"], "SMA50": ["sma50"], "SMA200": ["sma200"], "EMA12": ["ema12"], "EMA26": ["ema26"],
    "RSI14": ["rsi14"], "MACD": ["macd", "macd_signal", "macd_hist"],
    "BBANDS20": ["bb_upper", "bb_mid", "bb_lower"], "ATR14": ["atr14"], "VOL_SMA20": ["vol_sma20"],
}
PRICE_COLS = ["open", "high", "low", "close", "volume"]


def _parse_date(name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolInputError("INVALID_RANGE", f"{name} phải có dạng YYYY-MM-DD, nhận được {value!r}.")


def resolve_range(range_, start_date, end_date, as_of: date, today: date) -> tuple[date, date]:
    if range_ and (start_date or end_date):
        raise ToolInputError("INVALID_RANGE", "Chỉ dùng `range` hoặc `start_date`/`end_date`, không dùng cả hai.")
    if range_:
        if range_ not in RANGE_DAYS:
            raise ToolInputError("INVALID_RANGE", f"range không hợp lệ. Giá trị hợp lệ: {', '.join(RANGE_DAYS)}.")
        end = as_of
        return end - timedelta(days=RANGE_DAYS[range_]), end
    if not start_date:
        raise ToolInputError("INVALID_RANGE", f"Cần `range` ({', '.join(RANGE_DAYS)}) hoặc `start_date`.")
    start = _parse_date("start_date", start_date)
    end = _parse_date("end_date", end_date) if end_date else as_of
    if end > as_of or end > today or start > today:
        raise ToolInputError("FUTURE_DATE", f"Ngày vượt dữ liệu hiện có. as_of hiện tại là {as_of.isoformat()}.")
    if start > end:
        raise ToolInputError("INVALID_RANGE", "start_date không được sau end_date.")
    days = (end - start).days
    if days < MIN_DAYS:
        raise ToolInputError("RANGE_TOO_SHORT", f"Khoảng tùy chỉnh phải dài {MIN_DAYS}-{MAX_DAYS} ngày (nhận {days}). Gợi ý preset `1W`.")
    if days > MAX_DAYS:
        raise ToolInputError("RANGE_TOO_LONG", f"Khoảng tùy chỉnh phải dài {MIN_DAYS}-{MAX_DAYS} ngày (nhận {days}). Gợi ý preset `1Y`.")
    return start, end


def aggregate_weekly(df: pd.DataFrame, indicator_cols: list[str]) -> pd.DataFrame:
    """OHLCV gộp theo tuần ISO; chỉ báo lấy tại phiên cuối của tuần (không tính lại trên nến tuần)."""
    d = df.sort_values("trade_date").copy()
    iso = pd.to_datetime(d["trade_date"]).dt.isocalendar()
    d["_wk"] = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    g = d.groupby("_wk", sort=True)
    out = g.agg(trade_date=("trade_date", "last"), open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
    for c in indicator_cols:
        out[c] = g[c].last()
    return out.reset_index(drop=True)


def _iso(v) -> str:
    return pd.Timestamp(v).date().isoformat()


def _num(v, nd=4):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return round(float(v), nd)


def get_price_history(symbols, range=None, start_date=None, end_date=None, interval="1D",
                      indicators=None, path=None, today: date | None = None) -> dict:
    if not isinstance(symbols, list) or not symbols:
        raise ToolInputError("UNKNOWN_SYMBOL", "Cần danh sách `symbols` không rỗng. Gọi get_data_status để xem mã hợp lệ.")
    if len(symbols) > MAX_SYMBOLS:
        raise ToolInputError("TOO_MANY_SYMBOLS", f"Tối đa {MAX_SYMBOLS} mã mỗi lần gọi (nhận {len(symbols)}). Chia nhỏ yêu cầu.")
    if interval not in INTERVALS:
        raise ToolInputError("INVALID_RANGE", f"interval không hợp lệ. Giá trị hợp lệ: {', '.join(INTERVALS)}.")
    indicators = list(dict.fromkeys(indicators or []))
    unknown = [i for i in indicators if i not in INDICATORS]
    if unknown:
        raise ToolInputError("UNKNOWN_INDICATOR", f"Chỉ báo không hợp lệ: {', '.join(map(str, unknown))}. Hợp lệ: {', '.join(INDICATORS)}.")
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in symbols))
    ind_cols = [c for i in indicators for c in INDICATORS[i]]
    today = today or date.today()

    with db.reader(path) as con:
        pub = db.latest_published(con)
        as_of = pub["as_of"]
        start, end = resolve_range(range, start_date, end_date, as_of, today)
        universe = db.universe_status(con, pub["run_id"])
        unknown_syms = [s for s in symbols if s not in universe]
        if unknown_syms:
            raise ToolInputError("UNKNOWN_SYMBOL", f"Mã không có trong universe: {', '.join(unknown_syms)}. Gọi get_data_status để xem danh sách.")

        excluded, ok_syms = [], []
        for s in symbols:
            if universe[s]["status"] == "ok":
                ok_syms.append(s)
            else:
                excluded.append({"symbol": s, "status": universe[s]["status"],
                                 "reason": db.error_codes(con, pub["run_id"], s) or ["NOT_IN_LATEST_RUN"]})

        frames: dict[str, pd.DataFrame] = {}
        if ok_syms:
            ph = ",".join("?" * len(ok_syms))
            select = ", ".join(f"f.{c}" for c in ind_cols)
            sql = (f"SELECT p.symbol, p.trade_date, p.open, p.high, p.low, p.close, p.volume"
                   f"{', ' + select if select else ''} FROM prices_daily p "
                   f"LEFT JOIN features_daily f ON f.symbol = p.symbol AND f.trade_date = p.trade_date "
                   f"WHERE p.symbol IN ({ph}) AND p.trade_date BETWEEN ? AND ? ORDER BY p.symbol, p.trade_date")
            data = con.execute(sql, ok_syms + [start, end]).df()
            for s, g in data.groupby("symbol"):
                frames[s] = g.drop(columns="symbol").reset_index(drop=True)
            if interval == "1W":
                frames = {s: aggregate_weekly(g, ind_cols) for s, g in frames.items()}

        total_rows = sum(len(g) for g in frames.values())
        if total_rows > MAX_ROWS:
            raise ToolInputError("ROW_LIMIT_EXCEEDED", f"Kết quả {total_rows} dòng vượt giới hạn {MAX_ROWS}. Giảm số mã hoặc dùng interval=1W.")

        warnings: list[str] = []
        results = []
        for s in ok_syms:
            g = frames.get(s)
            if g is None or g.empty:
                warnings.append(f"{s}: không có dòng nào trong khoảng {start} đến {end}.")
                continue
            for name in indicators:
                for col in INDICATORS[name]:
                    nulls = int(g[col].isna().sum())
                    if nulls:
                        first = con.execute(
                            f"SELECT min(trade_date) FROM features_daily WHERE symbol = ? AND {col} IS NOT NULL", [s]).fetchone()[0]
                        when = f"có giá trị từ {first}" if first else "chưa có giá trị"
                        warnings.append(f"{s}: {col} null ở {nulls}/{len(g)} dòng (chưa đủ phiên; {when}).")
            first_close, last_close = float(g["close"].iloc[0]), float(g["close"].iloc[-1])
            cols = ["trade_date"] + PRICE_COLS + ind_cols
            rows = [[_iso(r[0])] + [_num(v, 2) if c in PRICE_COLS[:4] else (int(v) if c == "volume" else _num(v))
                                           for c, v in zip(cols[1:], r[1:])]
                    for r in g[cols].itertuples(index=False, name=None)]
            results.append({
                "symbol": s,
                "actual_range": {"start": _iso(g["trade_date"].iloc[0]), "end": _iso(g["trade_date"].iloc[-1])},
                "row_count": len(g),
                "summary": {
                    "first_close": _num(first_close, 2), "last_close": _num(last_close, 2),
                    "change_pct": _num((last_close / first_close - 1) * 100, 2),
                    "high": _num(g["high"].max(), 2), "low": _num(g["low"].min(), 2),
                    "avg_volume": _num(g["volume"].mean(), 0),
                },
                "columns": ["date"] + cols[1:],
                "rows": rows,
            })

        fv = con.execute("SELECT max(feature_version) FROM features_daily").fetchone()[0]
        return {
            "as_of": as_of.isoformat(),
            "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
            "interval": interval,
            "adjusted": True,
            "source": pub["provider"],
            "feature_version": fv,
            "results": results,
            "excluded_symbols": excluded,
            "warnings": warnings,
        }
