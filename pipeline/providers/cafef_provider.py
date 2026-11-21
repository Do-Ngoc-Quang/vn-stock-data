"""Adapter CafeF (thiết kế mục 4.4): mọi lời gọi tới cafef.vn nằm trong tệp này.

Endpoint nội bộ của trang web (không có tài liệu, có thể đổi): lịch sử giá, mỗi trang 30 dòng,
mỗi khoảng ngày chỉ trả tối đa ~1 năm, nên dùng chung `year_windows` rồi phân trang.
Giá mở/cao/thấp/đóng của nguồn là giá THÔ; chỉ `GiaDieuChinh` là giá đóng đã điều chỉnh.
Adapter nhân cả bốn giá với hệ số `GiaDieuChinh / GiaDongCua` của từng ngày.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Callable

import pandas as pd

from pipeline.errors import PermanentProviderError, TransientProviderError
from pipeline.providers.base import STANDARD_COLUMNS, FetchResult
from pipeline.providers.retry import Throttle, call_with_retry
from pipeline.providers.vnstock_provider import year_windows

URL = "https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/PriceHistory.ashx"
PRICE_FACTOR = 1000  # CafeF trả giá theo nghìn VND
EXCHANGES = ("HOSE", "HNX", "UPCOM")
MAX_PAGES = 40       # chặn vòng lặp vô hạn; 1 năm chỉ cần ~9 trang
RAW_COLUMNS = ["Symbol", "Ngay", "GiaMoCua", "GiaCaoNhat", "GiaThapNhat", "GiaDongCua",
               "GiaDieuChinh", "KhoiLuongKhopLenh"]


def normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    close = raw["GiaDongCua"].astype("float64")
    adj = raw["GiaDieuChinh"].astype("float64")
    # close <= 0 là dữ liệu hỏng: giữ hệ số 1 để validation báo NON_POSITIVE_PRICE thay vì chia cho 0
    ratio = (adj / close).where(close > 0, 1.0)
    out = pd.DataFrame({
        "symbol": symbol.upper(),
        "trade_date": pd.to_datetime(raw["Ngay"], format="%d/%m/%Y").dt.date,
    })
    for col, src in (("open", "GiaMoCua"), ("high", "GiaCaoNhat"), ("low", "GiaThapNhat"), ("close", "GiaDongCua")):
        out[col] = (raw[src].astype("float64") * ratio * PRICE_FACTOR).round(2).to_numpy()
    out["volume"] = raw["KhoiLuongKhopLenh"].fillna(0).astype("int64").to_numpy()
    out = out.drop_duplicates(subset="trade_date", keep="last").sort_values("trade_date")
    return out[STANDARD_COLUMNS].reset_index(drop=True)


def _http_page(symbol: str, start: date, end: date, page: int, exchange: str) -> dict:
    qs = urllib.parse.urlencode({
        "ExchangeType": exchange,  # sai sàn thì trả rỗng, không báo lỗi
        "Symbol": symbol.upper(),
        "StartDate": start.strftime("%m/%d/%Y"),  # định dạng MM/dd/yyyy; sai định dạng thì bị bỏ qua
        "EndDate": end.strftime("%m/%d/%Y"),
        "PageIndex": page,
        "PageSize": 30,  # nguồn cố định 30
    })
    req = urllib.request.Request(f"{URL}?{qs}", headers={"User-Agent": "vn-stock-data/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TransientProviderError(f"HTTP {exc.code}", rate_limited=exc.code == 429) from exc
    except (OSError, json.JSONDecodeError) as exc:  # OSError gồm URLError, TimeoutError, ConnectionResetError khi đọc phản hồi
        raise TransientProviderError(f"{type(exc).__name__}: {exc}") from exc


class CafefProvider:
    name = "cafef"
    source = "cafef"

    def __init__(
        self,
        calls_per_minute: float = 60,
        retry_attempts: int = 4,
        page_fetcher: Callable[[str, date, date, int, str], dict] | None = None,
        sleep=None,
        throttle: Throttle | None = None,
    ):
        import time

        self._sleep = sleep or time.sleep
        self._throttle = throttle or Throttle(calls_per_minute, sleep=self._sleep)
        self._attempts = retry_attempts
        self._fetch_page = page_fetcher or _http_page
        self._exchanges: dict[str, str] = {}

    @property
    def version(self) -> str:
        return "cafef-pricehistory-v1"

    def _page(self, symbol: str, start: date, end: date, page: int, exchange: str) -> dict:
        def call():
            self._throttle.wait()
            return self._fetch_page(symbol, start, end, page, exchange)

        return call_with_retry(call, attempts=self._attempts, sleep=self._sleep)

    def _window(self, symbol: str, start: date, end: date, exchange: str) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            body = self._page(symbol, start, end, page, exchange)
            data = body.get("Data") if isinstance(body, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get("Data"), list):
                raise PermanentProviderError("Phản hồi CafeF không đúng cấu trúc (endpoint có thể đã đổi)")
            rows.extend(data["Data"])
            if not data["Data"] or len(rows) >= int(data.get("TotalCount") or 0):
                return rows
        raise TransientProviderError(f"Quá {MAX_PAGES} trang cho {symbol} {start}..{end}")

    def fetch(self, symbol: str, start: date, end: date) -> FetchResult:
        rows: list[dict] = []
        exchange = self._exchanges.get(symbol.upper())
        for w_start, w_end in year_windows(start, end):
            if exchange is None:  # dò sàn ở cửa sổ gần nhất; mã không có dữ liệu ở sàn nào thì để rỗng
                for ex in EXCHANGES:
                    found = self._window(symbol, w_start, w_end, ex)
                    if found:
                        exchange = self._exchanges[symbol.upper()] = ex
                        rows.extend(found)
                        break
                continue
            rows.extend(self._window(symbol, w_start, w_end, exchange))  # một cửa sổ lỗi = cả mã lỗi
        raw = pd.DataFrame(rows) if rows else pd.DataFrame(columns=RAW_COLUMNS)  # raw giữ nguyên mọi trường nguồn trả về
        return FetchResult(raw=raw, prices=normalize(raw, symbol))
