# Thiết kế: MCP tool truy vấn dữ liệu giao dịch cho AI agent

- **Tài liệu liên quan:** `stock-pipeline-collection.md` (pipeline thu thập dữ liệu hàng tuần). MCP tool **chỉ đọc** các bảng do pipeline tạo ra, theo schema ở mục 6 của tài liệu đó.

---

## 1. Mục tiêu và phạm vi

### 1.1 Mục tiêu

Cho phép AI agent truy vấn dữ liệu giao dịch cổ phiếu Việt Nam trong một khoảng thời gian do agent chọn, **từ 1 tuần đến 1 năm**, kèm các chỉ báo kỹ thuật đã được tính sẵn, để phân tích và hỗ trợ ra quyết định mua/bán của người dùng.

### 1.2 Phạm vi giai đoạn đầu

- Hai tool: `get_price_history` và `get_data_status`.
- Dữ liệu cuối ngày (EOD), cập nhật mỗi tuần một lần.
- Chỉ báo chọn từ danh sách cố định (mục 2.3).

### 1.3 Ngoài phạm vi

- Dữ liệu trong phiên, streaming.
- Ghi dữ liệu, đặt lệnh hoặc giao dịch tự động.
- Tính chỉ báo theo yêu cầu với chu kỳ tùy ý.
- Tool tra cứu tổng hợp nhiều mã (ví dụ xếp hạng theo thay đổi giá): hoãn đến Giai đoạn 4, quyết định dựa trên log sử dụng thực tế.

---

## 2. Phụ thuộc vào pipeline

### 2.1 Những gì tool đọc

| Bảng | Dùng để |
|---|---|
| `runs` | Xác định lần chạy `published` mới nhất, `as_of`, trạng thái và thời điểm hoàn thành |
| `symbols` | Danh sách mã thuộc universe |
| `symbol_run_status` | Trạng thái từng mã (`ok` / `excluded` / `failed`), số dòng, ngày đầu/cuối |
| `prices_daily` | Giá OHLCV đã điều chỉnh (VND) |
| `features_daily` | Chỉ báo kỹ thuật tính sẵn |
| `quality_issues` | Lý do một mã bị loại (để đưa vào cảnh báo) |

### 2.2 Các cam kết mà tool dựa vào

Các điểm dưới đây do pipeline đảm bảo (xem mục 6 của `stock-pipeline-collection.md`). Nếu pipeline đổi, tài liệu này phải được cập nhật.

- Mọi giá là **VND**, đã điều chỉnh. `trade_date` theo ngày Việt Nam.
- **Công bố nguyên tử**: tool chỉ đọc dữ liệu thuộc lần chạy `published` mới nhất, không bao giờ đọc lần chạy dang dở hoặc thất bại.
- Chỉ báo là **null** khi chưa đủ số phiên để tính; tool không được thay null bằng 0.
- Lịch sử trong cơ sở dữ liệu tối thiểu 3 năm, đủ để tính `SMA200` cho khoảng `1Y`.
- Giá trị chỉ báo được tính trên **toàn bộ lịch sử** rồi mới cắt theo khoảng truy vấn, nên không phụ thuộc khoảng agent chọn.

### 2.3 Danh sách chỉ báo hỗ trợ

| Nhóm | Giá trị `indicators` | Cột trong `features_daily` |
|---|---|---|
| Xu hướng | `SMA20`, `SMA50`, `SMA200`, `EMA12`, `EMA26` | `sma20`, `sma50`, `sma200`, `ema12`, `ema26` |
| Động lượng | `RSI14`, `MACD` | `rsi14`; `macd`, `macd_signal`, `macd_hist` |
| Biến động | `BBANDS20`, `ATR14` | `bb_upper`, `bb_mid`, `bb_lower`; `atr14` |
| Khối lượng | `VOL_SMA20` | `vol_sma20` |

Thêm chỉ báo mới = thêm cột ở pipeline và thêm tên vào danh sách này.

---

## 3. Nguyên tắc thiết kế

1. **Chỉ đọc.** MCP server mở tệp DuckDB ở chế độ chỉ đọc (`read_only`); mã của server không có câu lệnh ghi nào.
2. **Truy vấn tham số hóa**, agent không gửi SQL tự do.
3. **Chỉ báo tính sẵn, không tính theo yêu cầu.** Cùng một mã, cùng một ngày thì mọi lần gọi đều ra cùng một con số, bất kể agent chọn khoảng nào. Hệ quả: `indicators` chỉ nhận danh sách cố định.
4. **Từ chối rõ ràng, không cắt ngầm.** Tham số sai thì trả lỗi kèm cách sửa, để agent tự điều chỉnh được.
5. **Trả đủ ngữ cảnh để agent không suy diễn sai**: ngày dữ liệu, khoảng thực có, mã bị loại, cảnh báo.
6. **Mô tả tool viết cho agent đọc**: nêu khi nào dùng, giới hạn nào áp dụng, giá trị hợp lệ là gì.

---

## 4. Tool `get_price_history`

**Mục đích:** lấy giá, khối lượng và (tùy chọn) chỉ báo của một hoặc nhiều mã trong một khoảng thời gian.

### 4.1 Tham số đầu vào

| Tham số | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `symbols` | mảng chuỗi | Có | Tối đa 10 mã. |
| `range` | enum | Một trong hai | `1W`, `2W`, `1M`, `3M`, `6M`, `1Y` (xem 4.2). |
| `start_date`, `end_date` | chuỗi ngày `YYYY-MM-DD` | Thay thế cho `range` | Khoảng tùy chỉnh. Không dùng cùng `range`. |
| `interval` | enum | Không (mặc định `1D`) | `1D` hoặc `1W` (xem 4.4). |
| `indicators` | mảng enum | Không | Chọn trong danh sách ở mục 2.3. |

### 4.2 Các mức `range`

| Preset | Khoảng | Số phiên xấp xỉ | Phù hợp với |
|---|---|---|---|
| `1W` | 7 ngày | ~5 | Diễn biến tuần vừa rồi, đột biến khối lượng |
| `2W` | 14 ngày | ~10 | Động lượng ngắn hạn, phản ứng sau tin tức |
| `1M` | 30 ngày | ~21 | Xu hướng ngắn hạn, SMA20, Bollinger 20 |
| `3M` | 90 ngày | ~63 | Xu hướng quý, SMA50 |
| `6M` | 180 ngày | ~125 | Xu hướng trung hạn, vùng hỗ trợ/kháng cự |
| `1Y` | 365 ngày | ~250 | SMA200, đỉnh/đáy 52 tuần |

(Số phiên chỉ là ước lượng, phụ thuộc lịch nghỉ lễ.)

Preset giúp agent không phải tự tính ngày, và gắn với mục đích phân tích nên agent chọn dễ hơn.

### 4.3 Quy tắc kiểm tra tham số

1. **Mốc kết thúc mặc định là `as_of`** (phiên mới nhất trong dữ liệu), không phải ngày hôm nay. Dữ liệu cập nhật hàng tuần nên neo vào "hôm nay" có thể cho khoảng trống.
2. Khoảng tùy chỉnh phải dài **từ 7 đến 365 ngày**. Ngoài khoảng này: từ chối, không tự cắt ngầm.
3. Không cho phép ngày tương lai; `start_date` không được sau `end_date`.
4. Tối đa **10 mã** mỗi lần gọi và tối đa **3.000 dòng** kết quả (giá trị khởi đầu, chỉnh theo kích thước kết quả thực tế).
5. Chỉ báo hoặc mã không hợp lệ: từ chối và liệt kê giá trị hợp lệ.

### 4.4 Hành vi khi `interval = 1W`

Chỉ báo vẫn là chỉ báo **tính trên dữ liệu ngày**, lấy giá trị tại **phiên giao dịch cuối cùng của mỗi tuần**. Không tính lại trên nến tuần, vì như vậy `RSI14` sẽ có nghĩa khác (14 tuần thay vì 14 phiên). Giá OHLCV của dòng tuần là tổng hợp của các phiên trong tuần: `open` của phiên đầu, `close` của phiên cuối, `high` lớn nhất, `low` nhỏ nhất, `volume` cộng dồn. Ghi rõ điều này trong mô tả tool để agent hiểu đúng.

Với khoảng `6M` và `1Y`, nên gợi ý `1W` khi agent chỉ cần xu hướng, vì 250 dòng mỗi mã cho nhiều mã dễ làm tràn ngữ cảnh.

### 4.5 Xử lý mã thiếu dữ liệu

- Mã mới niêm yết hoặc mới giao dịch lại có thể chưa đủ phiên cho một số chỉ báo (ví dụ `SMA200`). Khi đó trả **null** cho các dòng chưa tính được và thêm một mục vào `warnings` nêu chỉ báo nào, từ ngày nào mới có giá trị. Không điền 0.
- Mã bị loại do chưa qua kiểm tra chất lượng trong lần chạy hiện tại: không trả dữ liệu của mã đó, đưa vào `excluded_symbols` kèm lý do ngắn (lấy từ `quality_issues`).

### 4.6 Dữ liệu trả về

Dạng bảng gọn để tiết kiệm ngữ cảnh của agent.

```json
{
  "as_of": "2026-11-06",
  "requested_range": { "start": "2026-10-07", "end": "2026-11-06" },
  "interval": "1D",
  "adjusted": true,
  "source": "vnstock",
  "feature_version": "1",
  "results": [
    {
      "symbol": "FPT",
      "actual_range": { "start": "2026-10-07", "end": "2026-11-06" },
      "row_count": 22,
      "summary": {
        "first_close": 0,
        "last_close": 0,
        "change_pct": 0,
        "high": 0,
        "low": 0,
        "avg_volume": 0
      },
      "columns": ["date", "open", "high", "low", "close", "volume", "sma20", "rsi14"],
      "rows": [["2026-10-07", 0, 0, 0, 0, 0, null, null]]
    }
  ],
  "excluded_symbols": [],
  "warnings": []
}
```

Giải thích:
- `summary` do code tính: agent không cần tự tính các số này.
- `requested_range` và `actual_range` khác nhau khi mã mới niêm yết hoặc thiếu phiên.
- `excluded_symbols`: mã yêu cầu nhưng bị loại ở lần chạy hiện tại.
- `warnings`: ví dụ chỉ báo nào là null và từ ngày nào mới có giá trị.
- `feature_version`: phiên bản công thức chỉ báo, để truy vết khi công thức thay đổi.

---

## 5. Tool `get_data_status`

**Mục đích:** cho agent biết dữ liệu nào hỏi được, tránh hỏi bừa.

**Đầu ra:**
- `as_of`, `last_run_status`, `last_run_finished_at`.
- Danh sách mã trong universe kèm trạng thái (`ok`, `excluded`, `failed`), `first_date`, `last_date`, `row_count`.
- Danh sách chỉ báo và preset `range` hợp lệ.
- Nếu lần chạy mới nhất thất bại: cho biết dữ liệu đang phục vụ là của lần chạy `published` trước đó và `as_of` tương ứng.

Khuyến nghị agent gọi tool này trước khi truy vấn lần đầu trong một phiên làm việc (ghi vào mô tả tool).

---

## 6. Mã lỗi

| Mã | Khi nào | Hướng dẫn trong thông báo |
|---|---|---|
| `INVALID_RANGE` | `range` không thuộc enum, hoặc dùng cả `range` lẫn ngày | Nêu các preset hợp lệ |
| `RANGE_TOO_SHORT` / `RANGE_TOO_LONG` | Khoảng tùy chỉnh ngoài 7–365 ngày | Nêu khoảng cho phép, gợi ý preset gần nhất |
| `FUTURE_DATE` | Ngày sau `as_of` hoặc sau hôm nay | Nêu `as_of` hiện tại |
| `UNKNOWN_SYMBOL` | Mã không có trong universe | Gợi ý gọi `get_data_status` |
| `UNKNOWN_INDICATOR` | Chỉ báo ngoài danh sách | Liệt kê chỉ báo hợp lệ |
| `TOO_MANY_SYMBOLS` | Quá 10 mã | Chia nhỏ yêu cầu |
| `ROW_LIMIT_EXCEEDED` | Vượt giới hạn dòng | Giảm số mã hoặc dùng `interval = 1W` |
| `DATA_NOT_READY` | Chưa có lần chạy `published` nào | Báo rõ dữ liệu chưa sẵn sàng |

---

## 7. Triển khai và bảo mật

- MCP server chạy **cục bộ qua stdio**, do ứng dụng agent trên cùng máy khởi chạy. Không mở cổng mạng nên không cần xác thực.
- Mở `data/curated.duckdb` ở chế độ chỉ đọc, **mỗi yêu cầu một kết nối ngắn rồi đóng**, để pipeline đổi tên tệp khi công bố (`stock-pipeline-collection.md`, mục 6.5). Nếu tệp đang được thay, thử lại ngắn rồi mới báo lỗi.
- Truy vấn tham số hóa; không nối chuỗi từ đầu vào của agent.
- Đánh dấu cả hai tool là chỉ đọc trong mô tả MCP.
- Log yêu cầu (tham số, thời gian, kết quả/lỗi) phục vụ gỡ lỗi. Giới hạn số lần gọi mỗi phút là tùy chọn.
- Đường dẫn tệp DB lấy từ cấu hình hoặc biến môi trường, không đưa vào mô tả tool hay kết quả trả về.
- Nội dung trả về chỉ gồm số liệu và mã; không chứa văn bản tự do do bên ngoài kiểm soát (tránh đường vào cho chỉ dẫn độc hại tới agent). Trường `detail` trong `quality_issues` khi đưa vào cảnh báo chỉ dùng chuỗi do pipeline tự sinh.

---

## 8. Lộ trình (phần MCP tool)

Dùng chung đánh số giai đoạn với tài liệu pipeline.

**Giai đoạn 2 — MCP tool** *(bắt đầu sau khi pipeline công bố được `features_daily`)*
- MCP server với `get_price_history` và `get_data_status`.
- Kiểm thử các quy tắc ở 4.3 và mã lỗi ở mục 6, bao gồm các trường hợp: mã thiếu lịch sử, mã bị loại, chưa có lần chạy `published`, `interval = 1W`.
- Kiểm tra chéo: một số giá trị chỉ báo trả về so với tính độc lập bằng công cụ khác.

**Giai đoạn 3 — Củng cố**
- Log yêu cầu, đo kích thước kết quả thực tế để chỉnh giới hạn mục 4.3; giới hạn tốc độ nếu cần.

**Giai đoạn 4 — Mở rộng**
- Thêm tool/dữ liệu cho báo cáo tài chính khi pipeline có. Cân nhắc tool tổng hợp nhiều mã.

---

## 9. Rủi ro đã biết

| Rủi ro | Giảm thiểu |
|---|---|
| Agent diễn giải sai hoặc "bịa" số liệu | Chỉ báo và tổng hợp do code tính; kết quả kèm `as_of`, nguồn, cảnh báo; yêu cầu agent trích dẫn ngày dữ liệu |
| Agent hỏi sai khoảng hoặc chỉ báo vì không biết giới hạn | Lỗi nêu rõ cách sửa; `get_data_status` liệt kê giá trị hợp lệ; mô tả tool viết cho agent |
| Kết quả quá lớn làm tràn ngữ cảnh | Giới hạn số mã và số dòng; dạng bảng gọn; gợi ý `interval = 1W` |
| Agent coi null là 0 hoặc bỏ qua cảnh báo | Null giữ nguyên là null; cảnh báo nêu rõ chỉ báo và ngày bắt đầu có giá trị |
| Agent đọc dữ liệu cũ mà không biết | Mọi kết quả kèm `as_of`; `get_data_status` cho biết lần chạy mới nhất có thất bại không |
