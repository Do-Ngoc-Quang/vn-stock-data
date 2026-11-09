"""Kiểm tra độ sâu lịch sử vnstock trả về (điểm mở D11 trong docs/design).

Chạy trên máy có mạng và đã cài vnstock, từ thư mục gốc của repo:

    python scripts/check_history_depth.py
    python scripts/check_history_depth.py --symbol FPT --source VCI --years 5

Trả lời hai câu hỏi:
1. Một lần gọi cho khoảng 5 năm trả về từ ngày nào? (lần probe trước chỉ nhận về ~1 năm.)
2. Gọi riêng từng cửa sổ một năm trong quá khứ có lấy được không? Nếu có, có thể ghép
   nhiều lần gọi để lấy đủ lịch sử.

Nguồn giới hạn 10 lượt/phút nên mặc định nghỉ 7 giây giữa các lần gọi.
Báo cáo ghi vào data/probe/history_depth.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_vnstock import fetch_history, library_version  # noqa: E402


def span(df) -> dict:
    time_col = next((c for c in df.columns if str(c).lower() in ("time", "date")), None)
    if time_col is None or not len(df):
        return {"rows": int(len(df))}
    d = df[time_col]
    try:
        d = d.dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return {"rows": int(len(df)), "first": str(d.min().date()), "last": str(d.max().date())}


def attempt(symbol, source, start, end) -> dict:
    out = {"start": str(start), "end": str(end)}
    try:
        df, _ = fetch_history(symbol, source, str(start), str(end))
        out.update(span(df))
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="FPT")
    ap.add_argument("--source", default="VCI")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=7.0)
    ap.add_argument("--out", default="data/probe/history_depth.json")
    args = ap.parse_args()

    today = date.today()
    results = {"whole_range": None, "yearly_windows": []}

    print(f"1) Một lần gọi cho {args.years} năm ({args.symbol}/{args.source})")
    results["whole_range"] = attempt(args.symbol, args.source, today - timedelta(days=365 * args.years), today)
    print("  ", results["whole_range"])

    print("2) Từng cửa sổ một năm trong quá khứ")
    for k in range(1, args.years + 1):
        time.sleep(args.sleep)
        end = today - timedelta(days=365 * (k - 1))
        start = end - timedelta(days=364)
        r = attempt(args.symbol, args.source, start, end)
        results["yearly_windows"].append(r)
        print("  ", r)

    results.update({"run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "vnstock_version": library_version(),
                    "symbol": args.symbol, "source": args.source})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBáo cáo đầy đủ: {out}")


if __name__ == "__main__":
    main()
