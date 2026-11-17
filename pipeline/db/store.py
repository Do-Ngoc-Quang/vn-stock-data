"""Truy cập DuckDB và công bố nguyên tử (thiết kế mục 6.5)."""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.features.indicators import FEATURE_COLUMNS, FEATURE_VERSION

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
SERVING = "curated.duckdb"
STAGING = "curated.staging.duckdb"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def connect_with_retry(path: Path, attempts: int = 5, delay: float = 1.0, **kwargs) -> duckdb.DuckDBPyConnection:
    """Tệp có thể đang bị khóa (bên đọc); thử lại có giới hạn."""
    for i in range(attempts):
        try:
            return duckdb.connect(str(path), **kwargs)
        except duckdb.IOException:
            if i == attempts - 1:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")


def prepare_staging(data_dir: Path) -> Path:
    """Sao chép tệp đang phục vụ (nếu có) thành tệp tạm; chưa có thì tạo mới."""
    serving, staging = data_dir / SERVING, data_dir / STAGING
    for stale in (staging, data_dir / (STAGING + ".wal")):
        stale.unlink(missing_ok=True)
    if serving.exists():
        shutil.copy2(serving, staging)
    con = duckdb.connect(str(staging))
    try:
        init_schema(con)
    finally:
        con.close()
    return staging


def publish(data_dir: Path, attempts: int = 5, delay: float = 1.0) -> None:
    """Đổi tên tệp tạm thành tệp phục vụ (nguyên tử). Trên Windows thử lại khi tệp đang mở."""
    serving, staging = data_dir / SERVING, data_dir / STAGING
    for i in range(attempts):
        try:
            os.replace(staging, serving)
            (data_dir / (SERVING + ".wal")).unlink(missing_ok=True)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def discard_staging(data_dir: Path) -> None:
    for name in (STAGING, STAGING + ".wal"):
        (data_dir / name).unlink(missing_ok=True)


def _df(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def write_run_records(con, run: dict, statuses: list[dict], issues: list) -> None:
    """Ghi runs, symbol_run_status, quality_issues (một giao dịch)."""
    now = utcnow()
    con.execute("BEGIN")
    try:
        con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [run["run_id"], run["started_at"], run.get("finished_at"), run["status"], run.get("as_of_date"),
             run["provider"], run["provider_version"], run["symbols_total"], run["symbols_ok"],
             run["symbols_excluded"], run["symbols_failed"]],
        )
        for s in statuses:
            con.execute(
                "INSERT OR REPLACE INTO symbol_run_status VALUES (?,?,?,?,?,?)",
                [run["run_id"], s["symbol"], s["status"], s["row_count"], s["first_date"], s["last_date"]],
            )
        con.execute("DELETE FROM quality_issues WHERE run_id = ?", [run["run_id"]])
        for i in issues:
            con.execute("INSERT INTO quality_issues VALUES (?,?,?,?,?,?)",
                        [run["run_id"], i.symbol, i.check_code, i.severity, i.detail, now])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def upsert_symbols(con, universe: list[tuple[str, str | None]]) -> None:
    con.execute("UPDATE symbols SET in_universe = FALSE")
    for symbol, exchange in universe:
        con.execute(
            """INSERT INTO symbols (symbol, exchange, name, in_universe) VALUES (?, ?, NULL, TRUE)
               ON CONFLICT (symbol) DO UPDATE SET in_universe = TRUE,
                   exchange = COALESCE(excluded.exchange, symbols.exchange)""",
            [symbol, exchange],
        )


def upsert_prices(con, prices: pd.DataFrame, source: str, run_id: str) -> None:
    df = prices.copy()
    df["adjusted"] = True
    df["source"] = source
    df["run_id"] = run_id
    df = df[["symbol", "trade_date", "open", "high", "low", "close", "volume", "adjusted", "source", "run_id"]]
    con.register("_prices_in", df)
    try:
        con.execute("INSERT OR REPLACE INTO prices_daily SELECT * FROM _prices_in")
    finally:
        con.unregister("_prices_in")


def replace_features(con, symbol: str, features: pd.DataFrame, run_id: str) -> None:
    """Tính lại toàn bộ chỉ báo của mã: xóa cũ rồi ghi mới."""
    df = features.copy()
    df.insert(0, "symbol", symbol)
    df["feature_version"] = FEATURE_VERSION
    df["run_id"] = run_id
    df = df[["symbol", "trade_date"] + FEATURE_COLUMNS + ["feature_version", "run_id"]]
    con.execute("DELETE FROM features_daily WHERE symbol = ?", [symbol])
    con.register("_features_in", df)
    try:
        con.execute("INSERT INTO features_daily SELECT * FROM _features_in")
    finally:
        con.unregister("_features_in")
