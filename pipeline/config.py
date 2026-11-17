"""Đọc cấu hình và universe."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    provider: str = "vnstock"
    source: str = "vci"
    history_years: int = 2
    calls_per_minute: float = 8
    retry_attempts: int = 4
    failure_threshold: float = 0.10
    stale_days: int = 5
    market_close_hour_vn: int = 15
    short_history_rows: int = 200
    zero_volume_ratio: float = 0.10
    large_move_pct: dict = field(default_factory=lambda: {"default": 15.0})

    def move_threshold(self, exchange: str | None) -> float:
        return float(self.large_move_pct.get((exchange or "").upper(), self.large_move_pct["default"]))


def load_config(path: Path | str | None) -> Config:
    if path is None or not Path(path).exists():
        return Config()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
    return Config(**known)


def load_universe(path: Path | str) -> list[tuple[str, str | None]]:
    """Mỗi dòng: `MÃ` hoặc `MÃ SÀN`. Bỏ dòng trống và chú thích (#). Trả về [(symbol, exchange)]."""
    seen: dict[str, str | None] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        symbol = parts[0].upper()
        exchange = parts[1].upper() if len(parts) > 1 else None
        seen.setdefault(symbol, exchange)
    if not seen:
        raise ValueError(f"Universe rỗng: {path}")
    return list(seen.items())
