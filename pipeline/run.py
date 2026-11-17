"""Lệnh chạy pipeline: python -m pipeline.run (thiết kế mục 4.5)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from pipeline.config import Config, load_config, load_universe
from pipeline.db import raw as rawstore
from pipeline.db import store
from pipeline.errors import PermanentProviderError, ProviderError
from pipeline.features.indicators import compute_features
from pipeline.providers.base import DataProvider
from pipeline.report import build_report
from pipeline.validation.checks import Issue, check_coverage, check_stale, has_error, validate_symbol

VN = ZoneInfo("Asia/Ho_Chi_Minh")
log = logging.getLogger("pipeline")


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _write_last_run(data_dir: Path, payload: dict) -> None:
    tmp = data_dir / "last_run.json.tmp"
    tmp.write_text(json.dumps({k: _iso(v) for k, v in payload.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, data_dir / "last_run.json")


def _setup_logging(data_dir: Path, run_id: str) -> logging.Handler:
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(data_dir / "logs" / f"run-{run_id}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return handler


def run_pipeline(
    data_dir: Path,
    universe_path: Path,
    config: Config,
    provider: DataProvider,
    now: datetime | None = None,
) -> dict:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    now_vn = now.astimezone(VN)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    handler = _setup_logging(data_dir, run_id)
    try:
        return _run(data_dir, universe_path, config, provider, now, now_vn, run_id)
    finally:
        log.removeHandler(handler)
        handler.close()


def _run(data_dir, universe_path, cfg: Config, provider, now, now_vn, run_id) -> dict:
    run = {
        "run_id": run_id, "started_at": now, "finished_at": None, "status": "running", "as_of_date": None,
        "provider": provider.name, "provider_version": provider.version,
        "symbols_total": 0, "symbols_ok": 0, "symbols_excluded": 0, "symbols_failed": 0,
    }
    _write_last_run(data_dir, run)
    universe = load_universe(universe_path)
    run["symbols_total"] = len(universe)
    log.info("run %s: %d mã, nguồn %s %s/%s", run_id, len(universe), provider.name, provider.version, provider.source)

    today = now_vn.date()
    end = today
    start = end - timedelta(days=365 * cfg.history_years)
    # Trước giờ đóng cửa của ngày giao dịch (T2–T6): phiên hôm nay có thể chưa chốt
    drop_today = now_vn.hour < cfg.market_close_hour_vn and now_vn.weekday() < 5

    warnings: list[str] = []
    if drop_today:
        warnings.append(f"Chạy trước {cfg.market_close_hour_vn}:00 giờ Việt Nam: bỏ phiên {today} vì có thể chưa chốt")

    raw_frames, fetched_at = {}, {}
    prices, statuses, issues = {}, [], []
    for symbol, exchange in universe:
        status = {"symbol": symbol, "status": "failed", "row_count": 0, "first_date": None, "last_date": None}
        statuses.append(status)
        try:
            res = provider.fetch(symbol, start, end)
        except ProviderError as exc:
            kind = "vĩnh viễn" if isinstance(exc, PermanentProviderError) else "tạm thời"
            issues.append(Issue(symbol, "FETCH_FAILED", "error", f"lỗi {kind}: {str(exc)[:200]}"))
            log.warning("%s: lỗi lấy dữ liệu: %s", symbol, exc)
            continue
        raw_frames[symbol] = res.raw
        fetched_at[symbol] = datetime.now(timezone.utc)
        df = res.prices
        if drop_today and len(df):
            df = df[df["trade_date"] < today]
        found = validate_symbol(symbol, df, cfg, exchange)
        issues += found
        status.update(row_count=int(len(df)))
        if len(df):
            status.update(first_date=df["trade_date"].min(), last_date=df["trade_date"].max())
        if has_error(found):
            status["status"] = "excluded"
            log.warning("%s: bị loại: %s", symbol, "; ".join(i.check_code for i in found if i.severity == "error"))
        else:
            status["status"] = "ok"
            prices[symbol] = df
        log.info("%s: %s, %d dòng", symbol, status["status"], len(df))

    raw_file = None
    try:
        raw_file = rawstore.write_raw(data_dir, provider.source, f"{today:%Y-%m-%d}", run_id, raw_frames, fetched_at)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Không ghi được raw: {exc}")
        log.exception("ghi raw lỗi")

    run["symbols_ok"] = len(prices)
    run["symbols_excluded"] = sum(s["status"] == "excluded" for s in statuses)
    run["symbols_failed"] = sum(s["status"] == "failed" for s in statuses)
    last_dates = [s["last_date"] for s in statuses if s["status"] == "ok" and s["last_date"]]
    run["as_of_date"] = max(last_dates) if last_dates else None

    stale = check_stale(run["as_of_date"], today, cfg)
    if stale:
        issues.append(stale)
        warnings.append(stale.detail)
    coverage = check_coverage(run["symbols_total"], run["symbols_excluded"], run["symbols_failed"], cfg)
    if coverage:
        issues.append(coverage)

    failure_reason = coverage.detail if coverage else None
    staging = None
    if not failure_reason:
        try:
            staging = store.prepare_staging(data_dir)
            con = duckdb.connect(str(staging))
            try:
                con.execute("BEGIN")
                store.upsert_symbols(con, universe)
                for symbol, df in prices.items():
                    store.upsert_prices(con, df, provider.source, run_id)
                    store.replace_features(con, symbol, compute_features(df), run_id)
                con.execute("COMMIT")
                run["status"], run["finished_at"] = "published", datetime.now(timezone.utc)
                store.write_run_records(con, run, statuses, issues)
                con.execute("CHECKPOINT")
            finally:
                con.close()
            store.publish(data_dir)
        except Exception as exc:  # noqa: BLE001 - mọi lỗi ghi đều dẫn tới failed, không công bố
            log.exception("công bố lỗi")
            failure_reason = f"lỗi khi ghi/công bố: {type(exc).__name__}: {exc}"
            store.discard_staging(data_dir)
            run["status"] = "failed"
    else:
        run["status"] = "failed"

    if run["status"] == "failed":
        run["finished_at"] = datetime.now(timezone.utc)
        warnings.append(f"Lần chạy thất bại, không công bố: {failure_reason}")
        con = store.connect_with_retry(data_dir / store.SERVING)
        try:
            store.init_schema(con)
            store.write_run_records(con, run, statuses, issues)
            con.execute("CHECKPOINT")
        finally:
            con.close()

    report = build_report(run, statuses, issues, warnings)
    (data_dir / "logs").mkdir(exist_ok=True)
    (data_dir / "logs" / f"report-{run_id}.md").write_text(report, encoding="utf-8")
    summary = dict(run, warnings=warnings, raw_file=str(raw_file) if raw_file else None,
                   issues=[i.__dict__ for i in issues if i.severity == "error" or i.symbol is None])
    _write_last_run(data_dir, summary)
    return summary


def format_summary(s: dict) -> str:
    lines = [
        f"Lần chạy {s['run_id']}: {s['status'].upper()}",
        f"  as_of: {s['as_of_date']}",
        f"  mã: tổng {s['symbols_total']}, đạt {s['symbols_ok']}, bị loại {s['symbols_excluded']}, lỗi {s['symbols_failed']}",
    ]
    lines += [f"  cảnh báo: {w}" for w in s["warnings"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline.run", description="Chạy pipeline thu thập một lần")
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"))
    p.add_argument("--universe", default=os.environ.get("UNIVERSE_FILE", "config/universe.txt"))
    p.add_argument("--config", default=os.environ.get("PIPELINE_CONFIG", "config/pipeline.json"))
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    if cfg.provider != "vnstock":
        print(f"Provider không hỗ trợ: {cfg.provider}", file=sys.stderr)
        return 2
    from pipeline.providers.vnstock_provider import VnstockProvider

    provider = VnstockProvider(source=cfg.source, calls_per_minute=cfg.calls_per_minute, retry_attempts=cfg.retry_attempts)
    summary = run_pipeline(Path(args.data_dir), Path(args.universe), cfg, provider)
    print(format_summary(summary))
    return 0 if summary["status"] == "published" else 1


if __name__ == "__main__":
    sys.exit(main())
