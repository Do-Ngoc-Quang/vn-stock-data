import asyncio
import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from mcp_server.errors import ToolInputError
from mcp_server.tools.price_history import get_price_history
from mcp_server.tools.status import get_data_status
from pipeline.config import Config
from pipeline.errors import PermanentProviderError
from pipeline.run import run_pipeline
from tests.helpers import NOW, FakeProvider, make_prices

TODAY = date(2026, 11, 9)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mcp")
    uni = tmp / "u.txt"
    uni.write_text("AAA\nBBB\nNEW\nBAD\n")
    data = {"AAA": make_prices("AAA", seed=1), "BBB": make_prices("BBB", seed=2),
            "NEW": make_prices("NEW", n=30, seed=3), "BAD": make_prices("BAD", seed=4)}
    data["BAD"].loc[5, "volume"] = -1
    run_pipeline(tmp / "data", uni, Config(failure_threshold=0.5), FakeProvider(data), now=NOW)
    return tmp / "data", uni, data


def call(db, **kw):
    kw.setdefault("path", db[0] / "curated.duckdb")
    kw.setdefault("today", TODAY)
    return get_price_history(**kw)


def err(db, **kw):
    with pytest.raises(ToolInputError) as e:
        call(db, **kw)
    return e.value.code


def test_basic_range_and_summary(db):
    r = call(db, symbols=["aaa"], range="1M", indicators=["SMA20", "RSI14"])
    assert r["as_of"] == "2026-11-06" and r["adjusted"] is True and r["interval"] == "1D"
    assert r["requested_range"] == {"start": "2026-10-07", "end": "2026-11-06"}
    res = r["results"][0]
    assert res["columns"] == ["date", "open", "high", "low", "close", "volume", "sma20", "rsi14"]
    assert res["row_count"] == len(res["rows"]) and res["actual_range"]["end"] == "2026-11-06"
    closes = [row[4] for row in res["rows"]]
    assert res["summary"]["first_close"] == closes[0] and res["summary"]["last_close"] == closes[-1]
    assert res["summary"]["change_pct"] == pytest.approx((closes[-1] / closes[0] - 1) * 100, abs=0.01)
    assert all(row[6] is not None for row in res["rows"])  # đã đủ phiên: SMA20 có giá trị


def test_indicator_independent_of_range(db):
    a = call(db, symbols=["AAA"], range="1W", indicators=["SMA200"])["results"][0]["rows"][-1]
    b = call(db, symbols=["AAA"], range="1Y", indicators=["SMA200"])["results"][0]["rows"][-1]
    assert a[-1] == b[-1] and a[-1] is not None


def test_weekly_aggregation(db):
    d = call(db, symbols=["AAA"], range="3M", indicators=["RSI14"])["results"][0]
    w = call(db, symbols=["AAA"], range="3M", interval="1W", indicators=["RSI14"])["results"][0]
    assert w["row_count"] < d["row_count"] / 4 + 2
    daily = {row[0]: row for row in d["rows"]}
    first_week = w["rows"][1]  # tuần đầy đủ
    assert first_week[0] in daily and first_week[-1] == daily[first_week[0]][-1]  # chỉ báo tại phiên cuối tuần
    assert first_week[5] == sum(r[5] for r in d["rows"] if date.fromisoformat(r[0]).isocalendar()[:2] == date.fromisoformat(first_week[0]).isocalendar()[:2])


def test_missing_history_null_with_warning(db):
    r = call(db, symbols=["NEW"], range="1M", indicators=["SMA50"])
    assert all(row[-1] is None for row in r["results"][0]["rows"])
    assert any("sma50" in w and "chưa" in w for w in r["warnings"])


def test_excluded_symbol(db):
    r = call(db, symbols=["AAA", "BAD"], range="1W")
    assert [x["symbol"] for x in r["results"]] == ["AAA"]
    assert r["excluded_symbols"] == [{"symbol": "BAD", "status": "excluded", "reason": ["NEGATIVE_VOLUME"]}]


def test_custom_range_defaults_end_to_as_of(db):
    r = call(db, symbols=["AAA"], start_date="2026-10-01")
    assert r["requested_range"]["end"] == "2026-11-06"


@pytest.mark.parametrize("kw,code", [
    (dict(symbols=["AAA"], range="2Y"), "INVALID_RANGE"),
    (dict(symbols=["AAA"], range="1M", start_date="2026-10-01"), "INVALID_RANGE"),
    (dict(symbols=["AAA"]), "INVALID_RANGE"),
    (dict(symbols=["AAA"], start_date="2026-13-01"), "INVALID_RANGE"),
    (dict(symbols=["AAA"], start_date="2026-11-03", end_date="2026-11-06"), "RANGE_TOO_SHORT"),
    (dict(symbols=["AAA"], start_date="2025-01-01", end_date="2026-11-06"), "RANGE_TOO_LONG"),
    (dict(symbols=["AAA"], start_date="2026-10-01", end_date="2026-11-08"), "FUTURE_DATE"),
    (dict(symbols=["AAA"], start_date="2026-12-01"), "FUTURE_DATE"),
    (dict(symbols=["ZZZ"], range="1W"), "UNKNOWN_SYMBOL"),
    (dict(symbols=["AAA"], range="1W", indicators=["WILLIAMS"]), "UNKNOWN_INDICATOR"),
    (dict(symbols=[f"S{i}" for i in range(11)], range="1W"), "TOO_MANY_SYMBOLS"),
])
def test_error_codes(db, kw, code):
    assert err(db, **kw) == code


def test_row_limit(db, monkeypatch):
    import mcp_server.tools.price_history as ph
    monkeypatch.setattr(ph, "MAX_ROWS", 20)
    assert err(db, symbols=["AAA", "BBB"], range="1M") == "ROW_LIMIT_EXCEEDED"


def test_data_not_ready(tmp_path):
    with pytest.raises(ToolInputError) as e:
        get_price_history(["AAA"], range="1W", path=tmp_path / "nope.duckdb")
    assert e.value.code == "DATA_NOT_READY"
    con = duckdb.connect(str(tmp_path / "empty.duckdb"))
    from pipeline.db.store import init_schema
    init_schema(con); con.close()
    with pytest.raises(ToolInputError) as e:
        get_data_status(tmp_path / "empty.duckdb")
    assert e.value.code == "DATA_NOT_READY"


def test_status_and_failed_latest_run(db):
    data_dir, uni, data = db
    s = get_data_status(data_dir / "curated.duckdb")
    assert s["last_run_status"] == "published" and "note" not in s
    assert {x["symbol"]: x["status"] for x in s["symbols"]} == {"AAA": "ok", "BBB": "ok", "NEW": "ok", "BAD": "excluded"}
    assert "SMA200" in s["valid_indicators"] and "1Y" in s["valid_ranges"]
    errs = {k: PermanentProviderError("x") for k in ("AAA", "BBB", "NEW")}
    import shutil
    d2 = data_dir.parent / "data2"
    shutil.copytree(data_dir, d2)
    run_pipeline(d2, uni, Config(), FakeProvider(data, errs), now=datetime(2026, 11, 10, 9, tzinfo=timezone.utc))
    s = get_data_status(d2 / "curated.duckdb")
    assert s["last_run_status"] == "failed" and s["as_of"] == "2026-11-06" and "published trước" in s["note"]
    r = get_price_history(["AAA"], range="1W", path=d2 / "curated.duckdb", today=TODAY)  # vẫn phục vụ lần published trước
    assert r["results"][0]["row_count"] > 0


def test_server_registers_tools_and_reports_errors(db, monkeypatch):
    monkeypatch.setenv("STOCK_DB_PATH", str(db[0] / "curated.duckdb"))
    monkeypatch.setenv("MCP_LOG_FILE", str(db[0].parent / "req.jsonl"))
    from mcp_server.server import build_server
    srv = build_server()
    tools = {t.name: t for t in asyncio.run(srv.list_tools())}
    assert set(tools) == {"get_data_status", "get_price_history"}
    assert all(t.annotations.read_only_hint for t in tools.values())
    out = asyncio.run(srv.call_tool("get_price_history", {"symbols": ["AAA"], "range": "1W"}))
    assert not out.is_error if hasattr(out, "is_error") else True
    with pytest.raises(Exception) as e:
        asyncio.run(srv.call_tool("get_price_history", {"symbols": ["ZZZ"], "range": "1W"}))
    assert "UNKNOWN_SYMBOL" in str(e.value)
    lines = [json.loads(l) for l in (db[0].parent / "req.jsonl").read_text().splitlines()]
    assert lines[0]["outcome"] == "ok" and lines[0]["size_bytes"] > 0 and lines[1]["outcome"] == "UNKNOWN_SYMBOL"
