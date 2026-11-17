"""Tool get_data_status (thiết kế MCP mục 5)."""
from __future__ import annotations

from mcp_server import db
from mcp_server.tools.price_history import INDICATORS, RANGE_DAYS


def get_data_status(path=None) -> dict:
    with db.reader(path) as con:
        pub = db.latest_published(con)
        symbols = db.universe_status(con, pub["run_id"])
        latest = con.execute(
            "SELECT run_id, status, finished_at, as_of_date FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        out = {
            "as_of": pub["as_of"].isoformat(),
            "last_run_status": latest[1],
            "last_run_finished_at": latest[2].isoformat() if latest[2] else None,
            "published_run_finished_at": pub["finished_at"].isoformat() if pub["finished_at"] else None,
            "symbols": [
                {"symbol": s["symbol"], "status": s["status"], "first_date": _d(s["first_date"]),
                 "last_date": _d(s["last_date"]), "row_count": s["row_count"]}
                for s in symbols.values()
            ],
            "valid_indicators": list(INDICATORS),
            "valid_ranges": list(RANGE_DAYS),
            "valid_intervals": ["1D", "1W"],
        }
        if latest[0] != pub["run_id"]:
            out["note"] = (f"Lần chạy mới nhất ({latest[1]}) không được công bố; đang phục vụ dữ liệu của lần "
                           f"published trước với as_of {pub['as_of'].isoformat()}.")
        return out


def _d(v):
    return v.isoformat() if v else None
