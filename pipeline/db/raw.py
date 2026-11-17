"""Lớp raw: Parquet, không sửa không xóa (thiết kế mục 6.2)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def raw_path(data_dir: Path, source: str, run_date: str, run_id: str) -> Path:
    return data_dir / "raw" / "prices" / f"source={source}" / f"run_date={run_date}" / f"run_id={run_id}" / "prices.parquet"


def write_raw(data_dir: Path, source: str, run_date: str, run_id: str,
              frames: dict[str, pd.DataFrame], fetched_at: dict[str, datetime]) -> Path | None:
    parts = []
    for symbol, df in frames.items():
        if df is None or len(df) == 0:
            continue
        part = df.copy()
        part["symbol"] = symbol
        part["fetched_at"] = pd.Timestamp(fetched_at[symbol])
        part["run_id"] = run_id
        parts.append(part)
    if not parts:
        return None
    path = raw_path(data_dir, source, run_date, run_id)
    if path.exists():
        raise FileExistsError(f"raw không được ghi đè: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(parts, ignore_index=True).to_parquet(path, index=False)
    return path
