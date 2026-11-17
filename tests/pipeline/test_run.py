import json
from datetime import datetime, timezone

import duckdb
import pytest

from pipeline.backup import create_backup, restore_backup
from pipeline.config import Config
from pipeline.errors import PermanentProviderError
from pipeline.run import run_pipeline
from tests.helpers import NOW, FakeProvider, make_prices


@pytest.fixture
def env(tmp_path):
    uni = tmp_path / "universe.txt"
    uni.write_text("# test\nAAA HOSE\nBBB\nCCC\n", encoding="utf-8")
    data = {s: make_prices(s, seed=i) for i, s in enumerate(["AAA", "BBB", "CCC"], 1)}
    return tmp_path / "data", uni, data


def q(data_dir, sql, params=()):
    con = duckdb.connect(str(data_dir / "curated.duckdb"), read_only=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_publish_and_idempotent_rerun(env):
    data_dir, uni, data = env
    s1 = run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=NOW)
    assert s1["status"] == "published" and s1["symbols_ok"] == 3 and str(s1["as_of_date"]) == "2026-11-06"
    n_prices = q(data_dir, "SELECT count(*) FROM prices_daily")[0][0]
    n_feat = q(data_dir, "SELECT count(*) FROM features_daily")[0][0]
    assert n_prices == n_feat == 3 * 260
    s2 = run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=datetime(2026, 11, 9, 9, 1, tzinfo=timezone.utc))
    assert q(data_dir, "SELECT count(*) FROM prices_daily")[0][0] == n_prices  # không trùng
    assert q(data_dir, "SELECT count(*) FROM features_daily")[0][0] == n_feat
    assert q(data_dir, "SELECT count(*) FROM runs WHERE status='published'")[0][0] == 2
    # raw nguyên vẹn, riêng theo run_id; last_run.json và báo cáo có mặt
    assert s1["raw_file"] != s2["raw_file"] and all(__import__("pathlib").Path(x["raw_file"]).exists() for x in (s1, s2))
    assert json.loads((data_dir / "last_run.json").read_text())["status"] == "published"
    assert (data_dir / "logs" / f"report-{s1['run_id']}.md").exists()
    assert not (data_dir / "curated.staging.duckdb").exists()


def test_bad_symbol_excluded_with_issue(env):
    data_dir, uni, data = env
    data["BBB"].loc[10, "volume"] = -5
    cfg = Config(failure_threshold=0.5)
    s = run_pipeline(data_dir, uni, cfg, FakeProvider(data), now=NOW)
    assert s["status"] == "published" and s["symbols_excluded"] == 1
    assert q(data_dir, "SELECT status FROM symbol_run_status WHERE symbol='BBB'") == [("excluded",)]
    assert q(data_dir, "SELECT check_code FROM quality_issues WHERE symbol='BBB' AND severity='error'") == [("NEGATIVE_VOLUME",)]
    assert q(data_dir, "SELECT count(*) FROM prices_daily WHERE symbol='BBB'")[0][0] == 0


def test_failed_run_does_not_change_serving_data(env):
    data_dir, uni, data = env
    run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=NOW)
    before = q(data_dir, "SELECT symbol, trade_date, close, run_id FROM prices_daily ORDER BY 1,2")
    feats = q(data_dir, "SELECT * FROM features_daily ORDER BY 1,2")
    errs = {"BBB": PermanentProviderError("no"), "CCC": PermanentProviderError("no")}
    s = run_pipeline(data_dir, uni, Config(), FakeProvider(data, errs), now=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))
    assert s["status"] == "failed" and s["symbols_failed"] == 2
    assert q(data_dir, "SELECT symbol, trade_date, close, run_id FROM prices_daily ORDER BY 1,2") == before
    assert q(data_dir, "SELECT * FROM features_daily ORDER BY 1,2") == feats
    assert q(data_dir, "SELECT status FROM runs ORDER BY started_at") == [("published",), ("failed",)]
    assert q(data_dir, "SELECT count(*) FROM quality_issues WHERE run_id=? AND check_code='UNIVERSE_COVERAGE'", [s["run_id"]])[0][0] == 1
    assert json.loads((data_dir / "last_run.json").read_text())["status"] == "failed"
    assert not (data_dir / "curated.staging.duckdb").exists()


def test_crash_while_writing_leaves_serving_untouched(env, monkeypatch):
    data_dir, uni, data = env
    run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=NOW)
    before = q(data_dir, "SELECT count(*), sum(close) FROM prices_daily")
    from pipeline.db import store

    def boom(*a, **k):
        raise RuntimeError("đĩa đầy")
    monkeypatch.setattr(store, "replace_features", boom)
    s = run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))
    assert s["status"] == "failed"
    assert q(data_dir, "SELECT count(*), sum(close) FROM prices_daily") == before


def test_first_run_failure_creates_no_published_run(env):
    data_dir, uni, data = env
    errs = {k: PermanentProviderError("no") for k in data}
    s = run_pipeline(data_dir, uni, Config(), FakeProvider(data, errs), now=NOW)
    assert s["status"] == "failed"
    assert q(data_dir, "SELECT count(*) FROM runs WHERE status='published'")[0][0] == 0


def test_early_run_drops_today(env):
    data_dir, uni, data = env
    for s, df in data.items():  # thêm phiên hôm nay 2026-11-09
        row = df.iloc[[-1]].copy(); row["trade_date"] = datetime(2026, 11, 9).date(); df.loc[len(df)] = row.iloc[0]
    early = datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc)  # 09:00 giờ VN
    s = run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=early)
    assert str(s["as_of_date"]) == "2026-11-06" and any("bỏ phiên" in w for w in s["warnings"])
    s = run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=NOW)  # sau 15:00 giữ lại
    assert str(s["as_of_date"]) == "2026-11-09"


def test_universe_change_marks_in_universe(env):
    data_dir, uni, data = env
    run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=NOW)
    uni.write_text("AAA\nBBB\n")
    run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))
    assert q(data_dir, "SELECT symbol FROM symbols WHERE in_universe ORDER BY 1") == [("AAA",), ("BBB",)]


def test_backup_and_restore_roundtrip(env, tmp_path):
    data_dir, uni, data = env
    run_pipeline(data_dir, uni, Config(), FakeProvider(data), now=NOW)
    archive = create_backup(data_dir, tmp_path / "bk")
    expected = q(data_dir, "SELECT count(*), sum(close) FROM prices_daily")
    import shutil
    shutil.rmtree(data_dir)
    restore_backup(archive, data_dir)
    assert q(data_dir, "SELECT count(*), sum(close) FROM prices_daily") == expected
    assert list((data_dir / "raw").rglob("prices.parquet"))


def test_restore_rejects_path_traversal(tmp_path):
    import tarfile, io
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as t:
        info = tarfile.TarInfo("../x"); info.size = 1; t.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        restore_backup(evil, tmp_path / "d")
