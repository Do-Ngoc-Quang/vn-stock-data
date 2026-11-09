"""Probe vnstock để đóng D1 (docs/design/stock-pipeline-collection.md, mục 2.2).

Chạy trên máy có mạng và đã cài vnstock:

    python scripts/probe_vnstock.py --symbols FPT VCB --sources VCI TCBS

Kết quả: in bảng markdown để điền vào tài liệu và ghi data/probe/report.json.
Script chỉ đọc dữ liệu, không ghi vào curated.

Giới hạn: script thử API của vnstock thế hệ <= 5 (Vnstock().stock(...).quote.history)
và hàm cũ stock_historical_data. Nếu thư viện thế hệ 6 có giao diện khác, các lần thử
ghi lỗi vào báo cáo; khi đó sửa hàm `fetch_history` theo tài liệu thế hệ 6.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import traceback
from datetime import date, timedelta
from importlib import metadata
from pathlib import Path


def library_version() -> str | None:
    try:
        return metadata.version("vnstock")
    except metadata.PackageNotFoundError:
        return None


def fetch_history(symbol: str, source: str, start: str, end: str):
    """Trả về (DataFrame, tên cách gọi đã dùng). Ném ngoại lệ nếu mọi cách đều lỗi."""
    errors = []
    try:
        from vnstock import Vnstock

        df = Vnstock().stock(symbol=symbol, source=source).quote.history(
            start=start, end=end, interval="1D"
        )
        return df, "Vnstock().stock(...).quote.history"
    except Exception as exc:  # noqa: BLE001 - probe cần ghi lại mọi lỗi
        errors.append(f"Vnstock().stock: {type(exc).__name__}: {exc}")
    try:
        from vnstock import stock_historical_data

        df = stock_historical_data(symbol=symbol, start_date=start, end_date=end)
        return df, "stock_historical_data"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"stock_historical_data: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


def describe_frame(df) -> dict:
    cols = [str(c) for c in df.columns]
    info = {
        "columns": cols,
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
        "row_count": int(len(df)),
        "index_name": str(df.index.name),
    }
    close_col = next((c for c in df.columns if str(c).lower() == "close"), None)
    if close_col is not None and len(df):
        values = [float(v) for v in df[close_col].dropna()]
        if values:
            info["close_median"] = statistics.median(values)
            info["close_first"] = values[0]
            info["close_last"] = values[-1]
    if len(df):
        info["head"] = json.loads(df.head(2).to_json(orient="records", date_format="iso"))
        info["tail"] = json.loads(df.tail(2).to_json(orient="records", date_format="iso"))
    return info


def probe_one(symbol: str, source: str, days: int, calls: int) -> dict:
    end = date.today()
    start = end - timedelta(days=days)
    result: dict = {"symbol": symbol, "source": source, "start": str(start), "end": str(end)}
    latencies, failures = [], []
    first_df = None
    for i in range(calls):
        t0 = time.perf_counter()
        try:
            df, how = fetch_history(symbol, source, str(start), str(end))
            latencies.append(time.perf_counter() - t0)
            if first_df is None:
                first_df = df
                result["call_style"] = how
        except Exception as exc:  # noqa: BLE001
            latencies.append(time.perf_counter() - t0)
            failures.append({"call": i + 1, "error": f"{type(exc).__name__}: {exc}"})
    result["calls"] = calls
    result["failures"] = failures
    if latencies:
        result["latency_s"] = {
            "min": round(min(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "max": round(max(latencies), 3),
        }
    if first_df is not None:
        result.update(describe_frame(first_df))
        median = result.get("close_median")
        # Heuristic: cổ phiếu niêm yết VN thường có giá từ vài nghìn VND trở lên.
        # Giá trung vị < 1000 gợi ý đơn vị là nghìn VND. Chỉ là gợi ý, cần xem số thực.
        if median is not None:
            result["unit_hint"] = (
                "có thể là nghìn VND (trung vị close < 1000)"
                if median < 1000
                else "có thể là VND (trung vị close >= 1000)"
            )
    return result


def render_markdown(version: str | None, results: list[dict]) -> str:
    lines = [
        "| Mục kiểm tra | Kết quả |",
        "|---|---|",
        f"| Phiên bản vnstock | {version or 'KHÔNG CÀI ĐƯỢC / không tìm thấy'} |",
    ]
    for r in results:
        tag = f"{r['symbol']}/{r['source']}"
        if "columns" not in r:
            lines.append(f"| Lấy dữ liệu {tag} | THẤT BẠI: {r['failures'][:1]} |")
            continue
        lines.append(f"| Cột trả về {tag} | {', '.join(r['columns'])} (index: {r['index_name']}) |")
        lines.append(f"| Kiểu dữ liệu {tag} | {r['dtypes']} |")
        lines.append(
            f"| Đơn vị giá {tag} | close trung vị = {r.get('close_median')}; {r.get('unit_hint')} |"
        )
        lines.append(
            f"| Thời gian phản hồi {tag} | {r.get('latency_s')} giây/lần, "
            f"{len(r['failures'])}/{r['calls']} lần lỗi |"
        )
    lines.append("| Giá đã điều chỉnh hay chưa | Không xác định tự động; xem hướng dẫn kiểm tra thủ công trong báo cáo |")
    lines.append("| Nguồn bên dưới | Là tham số `source` đã dùng ở trên; đối chiếu với tài liệu thư viện |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="+", default=["FPT", "VCB"])
    ap.add_argument("--sources", nargs="+", default=["VCI", "TCBS"])
    ap.add_argument("--days", type=int, default=45, help="độ dài khoảng lấy thử (ngày)")
    ap.add_argument("--calls", type=int, default=5, help="số lần gọi liên tiếp mỗi cặp, để đo độ trễ và giới hạn")
    ap.add_argument("--out", default="data/probe/report.json")
    args = ap.parse_args()

    version = library_version()
    results = []
    for source in args.sources:
        for symbol in args.symbols:
            try:
                results.append(probe_one(symbol, source, args.days, args.calls))
            except Exception:  # noqa: BLE001
                results.append(
                    {"symbol": symbol, "source": source, "calls": 0,
                     "failures": [{"error": traceback.format_exc(limit=1)}]}
                )

    manual_adjusted_check = (
        "Chọn một mã đã có chia tách hoặc trả cổ tức bằng cổ phiếu trong vài năm gần đây. "
        "Lấy giá quanh ngày giao dịch không hưởng quyền: nếu giá liền kề ngày đó liên tục "
        "(không có bước nhảy tương ứng tỷ lệ chia) thì giá đã điều chỉnh."
    )
    report = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "vnstock_version": version,
        "results": results,
        "manual_adjusted_check": manual_adjusted_check,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(render_markdown(version, results))
    print(f"\nBáo cáo đầy đủ: {out}")
    print(f"Kiểm tra giá điều chỉnh (thủ công): {manual_adjusted_check}")


if __name__ == "__main__":
    main()
