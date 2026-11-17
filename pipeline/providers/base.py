"""Interface nguồn dữ liệu (thiết kế mục 4.4)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd

STANDARD_COLUMNS = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]


@dataclass
class FetchResult:
    raw: pd.DataFrame     # đúng như nguồn trả về (đã ghép các cửa sổ)
    prices: pd.DataFrame  # cột chuẩn STANDARD_COLUMNS, giá VND, đã điều chỉnh


class DataProvider(Protocol):
    name: str
    source: str

    @property
    def version(self) -> str: ...

    def fetch(self, symbol: str, start: date, end: date) -> FetchResult:
        """Ném TransientProviderError hoặc PermanentProviderError."""
        ...
