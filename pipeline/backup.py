"""Sao lưu và khôi phục data/ (Giai đoạn 3, thiết kế mục 9).

    python -m pipeline.backup create  --data-dir data --dest backups/
    python -m pipeline.backup restore --archive backups/data-XXXX.tar.gz --data-dir data
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

INCLUDE = ["curated.duckdb", "raw", "last_run.json"]


def create_backup(data_dir: Path, dest_dir: Path) -> Path:
    data_dir, dest_dir = Path(data_dir), Path(dest_dir)
    if not (data_dir / "curated.duckdb").exists() and not (data_dir / "raw").exists():
        raise FileNotFoundError(f"Không có dữ liệu để sao lưu trong {data_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / f"data-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in INCLUDE:
            if (data_dir / name).exists():
                tar.add(data_dir / name, arcname=name)
    return archive


def _safe_members(tar: tarfile.TarFile):
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
            raise ValueError(f"Thành phần không an toàn trong bản sao lưu: {m.name}")
        if parts[0] not in INCLUDE:
            raise ValueError(f"Thành phần không mong đợi: {m.name}")
        yield m


def restore_backup(archive: Path, data_dir: Path) -> None:
    """Giải nén vào thư mục tạm, kiểm tra DuckDB mở được, rồi mới thay vào data_dir."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir) as tmp:
        tmp = Path(tmp)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, members=list(_safe_members(tar)), filter="data")
        db = tmp / "curated.duckdb"
        if db.exists():
            con = duckdb.connect(str(db), read_only=True)
            try:
                con.execute("SELECT count(*) FROM runs").fetchone()
            finally:
                con.close()
        for name in INCLUDE:
            src, dst = tmp / name, data_dir / name
            if not src.exists():
                continue
            if dst.is_dir():
                shutil.rmtree(dst)
            elif dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline.backup")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--data-dir", default="data")
    c.add_argument("--dest", required=True)
    r = sub.add_parser("restore")
    r.add_argument("--archive", required=True)
    r.add_argument("--data-dir", default="data")
    a = p.parse_args(argv)
    if a.cmd == "create":
        print(create_backup(Path(a.data_dir), Path(a.dest)))
    else:
        restore_backup(Path(a.archive), Path(a.data_dir))
        print(f"Đã khôi phục vào {a.data_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
