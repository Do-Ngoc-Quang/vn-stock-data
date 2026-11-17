"""Mã lỗi của tool (thiết kế MCP mục 6)."""
import json


class ToolInputError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message

    def to_json(self) -> str:
        return json.dumps({"error": {"code": self.code, "message": self.message}}, ensure_ascii=False)
