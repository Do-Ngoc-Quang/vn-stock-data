"""Kiểm tra giá vnstock đã điều chỉnh hay chưa (phần còn lại của D1).

Chạy trên máy có mạng và đã cài vnstock, từ thư mục gốc của repo:

    python scripts/check_adjusted.py
    python scripts/check_adjusted.py --symbols FPT VNM HPG --sources VCI KBS --years 5

Ý tưởng, không cần biết trước ngày có sự kiện doanh nghiệp:

1. Kiểm tra bước nhảy. Trên HOSE, giá đóng cửa một phiên không thể lệch quá biên độ
   (±7%) so với phiên trước. Với giá CHƯA điều chỉnh, ngày giao dịch không hưởng quyền
   của cổ phiếu thưởng/chia tách lớn tạo một bước nhảy vượt biên độ (ví dụ thưởng 20%
   cho mức giảm khoảng 17%). Với giá ĐÃ điều chỉnh, các bước nhảy đó biến mất.
   Nhiều mã trong nhiều năm mà không có bước nhảy nào vượt biên độ là bằng chứng
   cho giá đã điều chỉnh. Có bước nhảy nghĩa là cần xem từng ngày (có thể là giá chưa
   điều chỉnh, hoặc phiên giao dịch lại sau thời gian dài bị ngừng, hoặc lỗi dữ liệu).

2. So sánh giữa các nguồn. Cùng một mã, cùng một ngày cũ, nếu một nguồn điều chỉnh
   còn nguồn kia không thì tỷ lệ giá khác 1 rõ rệt.

Mỗi cặp (mã, nguồn) là một lần gọi và nguồn giới hạn 10 lượt/phút, nên mặc định nghỉ 7 giây giữa các lần gọi.
Script chỉ đọc dữ liệu. Báo cáo ghi vào data/probe/adjusted_report.json.
Biên độ 7% là biên độ HOSE theo các nguồn tra cứu, chưa đối chiếu quy chế gốc (D8),
nên dùng mã niêm yết trên HOSE và có thể chỉnh bằng --limit.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_vnstock import fetch_history, library_version  # noqa: E402

# Mã lớn, niêm yết lâu năm trên HOSE. Có thể thay bằng --symbols.
DEFAULT_SYMBOLS = ["FPT", "VNM", "HPG", "MWG", "SSI", "REE", "PNJ", "VCB", "VIC", "MSN"]


def to_series(df):
    """DataFrame -> pandas.Series close, index là ngày theo múi giờ địa phương của cột time."""
    time_col = next((c for c in df.columns if str(c).lower() in ("time", "date")), None)
    if time_col is None:
        raise ValueError(f"không thấy cột thời gian trong {list(df.columns)}")
    dates = df[time_col]
    try:
        dates = dates.dt.tz_localize(None)  # giữ giờ địa phương, bỏ thông tin múi giờ
    except (TypeError, AttributeError):
        pass
    close = df["close"].astype(float).copy()
    close.index = dates.dt.date if hasattr(dates, "dt") else dates
    close = close[~close.index.duplicated(keep="last")].sort_index()
    return close


def find_jumps(close, limit: float, tolerance: float) -> list[dict]:
    ret = close.pct_change().dropna()
    out = []
    for d, r in ret.items():
        if abs(r) > limit + tolerance:
            out.append({"date": str(d), "return_pct": round(float(r) * 100, 2)})
    return out


def find_ratio_step(ratios: list[float], dates: list, window: int = 10, threshold: float = 0.0004):
    """Tìm ngày tỷ lệ giữa hai nguồn đổi mức (bước nhảy ổn định, không phải nhiễu làm tròn).

    So trung vị `window` ngày trước với `window` ngày sau tại từng ngày; trả về ngày có
    chênh lệch lớn nhất nếu vượt `threshold`. Ngày đó thường là ngày một nguồn bắt đầu
    áp điều chỉnh (ví dụ ngày giao dịch không hưởng quyền) còn nguồn kia thì không.
    """
    best = None
    for i in range(window, len(ratios) - window + 1):
        before = statistics.median(ratios[i - window:i])
        after = statistics.median(ratios[i:i + window])
        diff = after - before
        if best is None or abs(diff) > abs(best[0]):
            best = (diff, i, before, after)
    if best is None or abs(best[0]) <= threshold:
        return None
    diff, i, before, after = best
    return {"date": str(dates[i]), "ratio_before": round(before, 4), "ratio_after": round(after, 4)}


def compare_sources(series_by_source: dict) -> list[dict]:
    rows = []
    names = list(series_by_source)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = sorted(set(series_by_source[a].index) & set(series_by_source[b].index))
            if not common:
                continue
            ratios = [float(series_by_source[a][d] / series_by_source[b][d]) for d in common]
            rows.append({
                "pair": f"{a}/{b}",
                "common_days": len(common),
                "ratio_oldest": round(ratios[0], 4),
                "ratio_newest": round(ratios[-1], 4),
                "ratio_median": round(statistics.median(ratios), 4),
                "oldest_date": str(common[0]),
                "step": find_ratio_step(ratios, common),
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--sources", nargs="+", default=["VCI", "KBS"])
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--limit", type=float, default=0.07, help="biên độ giá/phiên (HOSE: 0.07)")
    ap.add_argument("--tolerance", type=float, default=0.005, help="dung sai cho làm tròn bước giá")
    ap.add_argument("--sleep", type=float, default=7.0,
                    help="nghỉ giữa các lần gọi (giây); vnstock 5.2.2 giới hạn 10 lượt/phút")
    ap.add_argument("--out", default="data/probe/adjusted_report.json")
    args = ap.parse_args()

    end = date.today()
    start = end - timedelta(days=365 * args.years)
    report = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "vnstock_version": library_version(),
              "range": [str(start), str(end)], "limit": args.limit, "symbols": {}}
    total_jumps = {s: 0 for s in args.sources}
    fetch_errors = []

    for symbol in args.symbols:
        per_source, series = {}, {}
        for source in args.sources:
            t0 = time.perf_counter()
            try:
                df, _ = fetch_history(symbol, source, str(start), str(end))
                close = to_series(df)
                jumps = find_jumps(close, args.limit, args.tolerance)
                series[source] = close
                per_source[source] = {"rows": int(len(close)), "first": str(close.index[0]),
                                      "last": str(close.index[-1]), "jumps": jumps,
                                      "seconds": round(time.perf_counter() - t0, 2)}
                total_jumps[source] += len(jumps)
            except Exception as exc:  # noqa: BLE001 - probe cần ghi lại mọi lỗi
                per_source[source] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                fetch_errors.append(f"{symbol}/{source}")
            time.sleep(args.sleep)
        report["symbols"][symbol] = {"sources": per_source, "cross_source": compare_sources(series)}

    ok_symbols = [s for s, v in report["symbols"].items()
                  if any("rows" in x for x in v["sources"].values())]
    report["summary"] = {"total_jumps_by_source": total_jumps, "fetch_errors": fetch_errors,
                         "symbols_with_data": len(ok_symbols)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"vnstock {report['vnstock_version']} | {start} → {end} | biên độ {args.limit:.0%}")
    print(f"Mã có dữ liệu: {len(ok_symbols)}/{len(args.symbols)}; lỗi lấy dữ liệu: {fetch_errors or 'không'}\n")
    for symbol, v in report["symbols"].items():
        for source, info in v["sources"].items():
            if "error" in info:
                print(f"{symbol:5} {source:4} LỖI {info['error']}")
                continue
            print(f"{symbol:5} {source:4} {info['rows']:5} dòng, {len(info['jumps'])} bước nhảy > {args.limit:.0%}"
                  + (f": {info['jumps'][:5]}" if info["jumps"] else ""))
        for c in v["cross_source"]:
            print(f"      so nguồn {c['pair']}: ngày cũ nhất {c['oldest_date']} tỷ lệ {c['ratio_oldest']}, "
                  f"mới nhất {c['ratio_newest']}, trung vị {c['ratio_median']}")
            if c.get("step"):
                st = c["step"]
                print(f"      bước đổi mức tỷ lệ quanh {st['date']}: {st['ratio_before']} → {st['ratio_after']} "
                      "(một nguồn điều chỉnh từ ngày này, nguồn kia thì không)")

    print("\nCách đọc kết quả:")
    for source, n in total_jumps.items():
        if not ok_symbols:
            verdict = "không có dữ liệu để kết luận"
        elif n == 0:
            verdict = ("không có bước nhảy nào vượt biên độ: phù hợp với giá ĐÃ điều chỉnh "
                       "(vẫn nên xác nhận thêm bằng tỷ lệ giữa các nguồn)")
        else:
            verdict = (f"{n} bước nhảy vượt biên độ: xem từng ngày. Nếu rơi đúng ngày giao dịch "
                       "không hưởng quyền với mức giảm bằng tỷ lệ thưởng/chia thì giá CHƯA điều chỉnh")
        print(f"- {source}: {verdict}")
    print("- So nguồn: tỷ lệ ~1.0 ở cả ngày cũ lẫn mới nghĩa là hai nguồn cùng cách điều chỉnh; "
          "tỷ lệ lệch ở ngày cũ nhưng ~1.0 ở ngày mới nghĩa là một nguồn có điều chỉnh, nguồn kia không.")
    print(f"\nBáo cáo đầy đủ: {out}")


if __name__ == "__main__":
    main()
