"""Bảng đăng ký nhà cung cấp dữ liệu.

Thêm nguồn mới: viết adapter theo `DataProvider`, thêm một hàm tạo vào PROVIDERS,
rồi đổi "provider" trong config/pipeline.json.
"""
from __future__ import annotations

from typing import Callable

from pipeline.config import Config
from pipeline.providers.base import DataProvider


def _vnstock(cfg: Config) -> DataProvider:
    # import muộn để không bắt buộc cài vnstock khi dùng nguồn khác
    from pipeline.providers.vnstock_provider import VnstockProvider

    return VnstockProvider(
        source=cfg.source,
        calls_per_minute=cfg.calls_per_minute,
        retry_attempts=cfg.retry_attempts,
    )


def _cafef(cfg: Config) -> DataProvider:
    from pipeline.providers.cafef_provider import CafefProvider

    return CafefProvider(calls_per_minute=cfg.calls_per_minute, retry_attempts=cfg.retry_attempts)


PROVIDERS: dict[str, Callable[[Config], DataProvider]] = {
    "vnstock": _vnstock,
    "cafef": _cafef,
}


def create_provider(cfg: Config) -> DataProvider:
    try:
        factory = PROVIDERS[cfg.provider]
    except KeyError:
        valid = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"Provider không hỗ trợ: {cfg.provider!r} (hợp lệ: {valid})") from None
    return factory(cfg)
