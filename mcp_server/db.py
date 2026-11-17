"""Truy cập DuckDB chỉ đọc: mỗi yêu cầu một kết nối ngắn rồi đóng (thiết kế MCP mục 7)."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

from mcp_server.errors import ToolInputError


def db_path() -> Path:
    return Path(os.environ.get("STOCK_DB_PATH", "data/curated.duckdb"))


@contextmanager
def reader(path: Path | None = None, attempts: int = 4, delay: float = 0.3):
    path = Path(path or db_path())
    if not path.exists():
        raise ToolInputError("DATA_NOT_READY", "Dữ liệu chưa sẵn sàng: pipeline chưa công bố lần chạy nào.")
    con = None
    for i in range(attempts):
        try:
            con = duckdb.connect(str(path), read_only=True)
            break
        except duckdb.IOException:
            if i == attempts - 1:
                raise
            time.sleep(delay)
    try:
        yield con
    finally:
        con.close()


def latest_published(con) -> dict:
    try:
        row = con.execute(
            "SELECT run_id, as_of_date, finished_at, provider FROM runs WHERE status = 'published' "
            "ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
    except duckdb.CatalogException:
        row = None
    if not row:
        raise ToolInputError("DATA_NOT_READY", "Dữ liệu chưa sẵn sàng: chưa có lần chạy published nào.")
    return {"run_id": row[0], "as_of": row[1], "finished_at": row[2], "provider": row[3]}


def universe_status(con, run_id: str) -> dict[str, dict]:
    """Trạng thái từng mã trong universe theo lần chạy published mới nhất."""
    rows = con.execute(
        """SELECT s.symbol, COALESCE(r.status, 'failed'), r.row_count, r.first_date, r.last_date
           FROM symbols s LEFT JOIN symbol_run_status r ON r.symbol = s.symbol AND r.run_id = ?
           WHERE s.in_universe ORDER BY s.symbol""",
        [run_id],
    ).fetchall()
    return {r[0]: {"symbol": r[0], "status": r[1], "row_count": r[2], "first_date": r[3], "last_date": r[4]} for r in rows}


def error_codes(con, run_id: str, symbol: str) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT check_code FROM quality_issues WHERE run_id = ? AND symbol = ? AND severity = 'error' ORDER BY 1",
        [run_id, symbol],
    ).fetchall()
    return [r[0] for r in rows]
