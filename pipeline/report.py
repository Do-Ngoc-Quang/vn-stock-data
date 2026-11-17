"""Báo cáo chất lượng dữ liệu theo từng lần chạy (Giai đoạn 3)."""
from __future__ import annotations

from collections import Counter


def build_report(run: dict, statuses: list[dict], issues: list, warnings: list[str]) -> str:
    L: list[str] = []
    L.append(f"# Báo cáo chất lượng dữ liệu — lần chạy `{run['run_id']}`\n")
    L.append(f"- Trạng thái: **{run['status']}**")
    L.append(f"- as_of: {run.get('as_of_date')}")
    L.append(f"- Nguồn: {run['provider']} {run['provider_version']}")
    L.append(f"- Bắt đầu: {run['started_at']}  Kết thúc: {run.get('finished_at')}")
    L.append(f"- Mã: tổng {run['symbols_total']}, đạt {run['symbols_ok']}, bị loại {run['symbols_excluded']}, lỗi lấy dữ liệu {run['symbols_failed']}\n")

    if warnings:
        L.append("## Cảnh báo của lần chạy\n")
        L += [f"- {w}" for w in warnings]
        L.append("")

    by_code = Counter((i.check_code, i.severity) for i in issues)
    L.append("## Tổng hợp kiểm tra\n")
    if by_code:
        L.append("| Mã kiểm tra | Mức | Số mã |")
        L.append("|---|---|---|")
        for (code, sev), n in sorted(by_code.items()):
            L.append(f"| {code} | {sev} | {n} |")
    else:
        L.append("Không có vấn đề nào.")
    L.append("")

    bad = [s for s in statuses if s["status"] != "ok"]
    if bad:
        L.append("## Mã không vào curated\n")
        L.append("| Mã | Trạng thái | Lý do |")
        L.append("|---|---|---|")
        for s in sorted(bad, key=lambda s: s["symbol"]):
            why = "; ".join(f"{i.check_code}: {i.detail}" for i in issues if i.symbol == s["symbol"] and i.severity == "error")
            L.append(f"| {s['symbol']} | {s['status']} | {why} |")
        L.append("")

    warns = [i for i in issues if i.severity == "warn" and i.symbol]
    if warns:
        L.append("## Cảnh báo theo mã\n")
        L.append("| Mã | Kiểm tra | Chi tiết |")
        L.append("|---|---|---|")
        for i in sorted(warns, key=lambda i: (i.symbol, i.check_code)):
            L.append(f"| {i.symbol} | {i.check_code} | {i.detail} |")
        L.append("")
    return "\n".join(L)
