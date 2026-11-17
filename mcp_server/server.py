"""MCP server stdio: python -m mcp_server.server (thiết kế MCP mục 7)."""
from __future__ import annotations

import json
import os
import sys
import time

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from mcp_server.errors import ToolInputError
from mcp_server.tools.price_history import INDICATORS, MAX_ROWS, MAX_SYMBOLS, RANGE_DAYS, get_price_history
from mcp_server.tools.status import get_data_status

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


STATUS_DESC = (
    "Cho biết dữ liệu nào hỏi được: as_of, trạng thái lần chạy gần nhất, từng mã trong universe "
    "(ok/excluded/failed, khoảng ngày, số dòng), chỉ báo và range hợp lệ. Chỉ đọc. Gọi tool này trước khi "
    "truy vấn lần đầu trong một phiên. Nếu lần chạy mới nhất thất bại, dữ liệu phục vụ là của lần published trước."
)
HISTORY_DESC = (
    f"Lấy giá OHLCV đã điều chỉnh (VND) và chỉ báo tính sẵn của 1-{MAX_SYMBOLS} mã. Chỉ đọc. "
    f"Khoảng thời gian: `range` thuộc {list(RANGE_DAYS)} HOẶC `start_date`/`end_date` (YYYY-MM-DD, dài 7-365 ngày); "
    "mốc kết thúc mặc định là as_of (phiên mới nhất có dữ liệu), không phải hôm nay. "
    "`interval`: `1D` hoặc `1W`. Với `1W`, OHLCV là tổng hợp theo tuần (open phiên đầu, close phiên cuối, high max, "
    "low min, volume cộng) còn chỉ báo vẫn tính trên dữ liệu NGÀY và lấy tại phiên cuối tuần. Nên dùng `1W` cho 6M/1Y. "
    f"`indicators` chọn trong {list(INDICATORS)}; giá trị null nghĩa là chưa đủ phiên để tính, KHÔNG phải 0. "
    f"Tối đa {MAX_ROWS} dòng mỗi lần. Kết quả có `summary` do code tính; hãy trích dẫn `as_of` khi diễn giải."
)


def log_request(tool: str, params: dict, started: float, outcome: str, result=None) -> None:
    """Một dòng JSON mỗi yêu cầu, kèm kích thước kết quả để chỉnh giới hạn (Giai đoạn 3).
    Ghi ra stderr (stdout là kênh giao thức) hoặc tệp MCP_LOG_FILE nếu đặt."""
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "params": params,
             "ms": round((time.monotonic() - started) * 1000, 1), "outcome": outcome}
    if result is not None:
        entry["size_bytes"] = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        if isinstance(result, dict) and "results" in result:
            entry["row_count"] = sum(r["row_count"] for r in result["results"])
    line = json.dumps(entry, ensure_ascii=False)
    path = os.environ.get("MCP_LOG_FILE")
    try:
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return
    except OSError:
        pass
    print(line, file=sys.stderr, flush=True)


def _guard(tool: str, params: dict, fn):
    started = time.monotonic()
    try:
        result = fn()
    except ToolInputError as exc:
        log_request(tool, params, started, exc.code)
        raise ToolError(exc.to_json()) from None
    log_request(tool, params, started, "ok", result)
    return result


def build_server() -> MCPServer:
    mcp = MCPServer(
        "vn-stock-data",
        instructions="Dữ liệu EOD cổ phiếu Việt Nam (giá VND đã điều chỉnh). Gọi get_data_status trước khi truy vấn lần đầu.",
    )

    @mcp.tool(name="get_data_status", description=STATUS_DESC, annotations=READ_ONLY)
    def data_status() -> dict:
        return _guard("get_data_status", {}, get_data_status)

    @mcp.tool(name="get_price_history", description=HISTORY_DESC, annotations=READ_ONLY)
    def price_history(
        symbols: list[str],
        range: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: str = "1D",
        indicators: list[str] | None = None,
    ) -> dict:
        params = {"symbols": symbols, "range": range, "start_date": start_date, "end_date": end_date,
                  "interval": interval, "indicators": indicators}
        return _guard("get_price_history", params, lambda: get_price_history(
            symbols, range, start_date, end_date, interval, indicators))

    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
