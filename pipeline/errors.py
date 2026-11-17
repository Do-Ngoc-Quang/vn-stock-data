"""Ngoại lệ phân loại của DataProvider (thiết kế mục 4.4)."""


class ProviderError(Exception):
    """Lỗi nguồn dữ liệu."""


class TransientProviderError(ProviderError):
    """Lỗi tạm thời, thử lại được. rate_limited=True khi vượt hạn mức theo phút."""

    def __init__(self, message: str, rate_limited: bool = False):
        super().__init__(message)
        self.rate_limited = rate_limited


class PermanentProviderError(ProviderError):
    """Lỗi vĩnh viễn (ví dụ mã không tồn tại), không thử lại."""
