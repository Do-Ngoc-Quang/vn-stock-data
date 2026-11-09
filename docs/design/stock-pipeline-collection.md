# Thiết kế: Pipeline thu thập dữ liệu giao dịch chứng khoán Việt Nam (hàng tuần)

- **Trạng thái:** Bản nháp thiết kế (chưa có code)
- **Ngày:** 2026-11-09
- **Tài liệu liên quan:** `stock-mcp-tool.md` (MCP tool để AI agent truy vấn dữ liệu). Hai tài liệu nối với nhau **chỉ qua schema ở mục 6** của tài liệu này.

---

## 1. Mục tiêu và phạm vi

### 1.1 Mục tiêu

Xây dựng một nguồn dữ liệu đáng tin cậy ("nguồn sự thật") về giao dịch cổ phiếu Việt Nam để AI agent truy vấn, phân tích insight và hỗ trợ ra quyết định mua/bán của người dùng. Tài liệu này chỉ nói về **phía sản xuất dữ liệu**: từ nguồn bên ngoài đến các bảng đã làm sạch.

### 1.2 Phạm vi giai đoạn đầu

- Thị trường: Việt Nam (HOSE, HNX, UPCoM).
- Dữ liệu: giá và khối lượng giao dịch hàng ngày (OHLCV), đã điều chỉnh.
- Tần suất cập nhật: **mỗi tuần một lần, Thứ 6 lúc 18:00 (giờ Việt Nam)**.
- Chỉ báo kỹ thuật tính sẵn (mục 6.4).

### 1.3 Ngoài phạm vi

- Dữ liệu trong phiên (intraday) và streaming.
- Đặt lệnh hoặc giao dịch tự động.
- Báo cáo tài chính và dữ liệu vĩ mô (để giai đoạn sau, mục 8).
- Đưa ra lời khuyên đầu tư. Hệ thống chỉ cung cấp dữ liệu; quyết định cuối cùng thuộc về người dùng.

### 1.4 Nguyên tắc thiết kế

1. **Số liệu do code tính, AI chỉ diễn giải.**
2. **Dữ liệu sai thì không nạp**, và hệ thống phải ghi lại dữ liệu nào bị loại.
3. **Cô lập nguồn dữ liệu sau một interface**, để đổi nguồn không ảnh hưởng phần còn lại.
4. **Giữ bản raw nguyên vẹn** để truy vết khi nghi ngờ số liệu.
5. **Mỗi lần chạy phải idempotent** (chạy lại cho cùng kết quả).
6. **Công bố dữ liệu theo kiểu nguyên tử**: bên đọc không bao giờ thấy dữ liệu của một lần chạy còn dang dở.

---

## 2. Nguồn dữ liệu

### 2.1 Lựa chọn

| Nguồn | Vai trò | Ghi chú |
|---|---|---|
| **vnstock** (Python, miễn phí) | Nguồn chính | Lấy dữ liệu từ các API công khai của công ty chứng khoán, nên nguồn bên dưới có thể thay đổi. |
| **SSI FastConnect Data** | Nguồn đối chiếu (tùy chọn) | API chính thức, có dữ liệu EOD và realtime. Đăng ký cần đến chi nhánh SSI hoặc gửi hồ sơ. |
| **Yahoo Finance (`.VN`)** | Không dùng làm nguồn chính | Đã quan sát một trang mã Việt Nam hiển thị giá VND kèm nhãn tiền tệ USD, nên không đáng tin làm nguồn sự thật. |

### 2.2 Cần xác minh về vnstock trước khi xây dựng

Khi tra cứu ngày 2026-11-09:

- Bản **3.2.4 trên PyPI bị quarantine** (không cài được) và trang liệt kê bản mới hơn **4.0.8**, nên tài liệu cũ có thể không còn khớp API hiện tại.
- Tài liệu bản cũ **không nêu** các cột trả về, đơn vị giá (VND hay nghìn VND) và giới hạn tốc độ gọi.

Vì vậy bước đầu tiên là **script probe** (mục 8, Giai đoạn 0): chạy vnstock bản hiện tại trên 1–2 mã và ghi lại tên cột, đơn vị giá, thời gian phản hồi. Kết quả được điền vào mục 2.3.

### 2.3 Kết quả probe (điền sau khi chạy)

| Mục kiểm tra | Kết quả |
|---|---|
| Phiên bản vnstock | _chưa kiểm tra_ |
| Tên các cột trả về của dữ liệu giá | _chưa kiểm tra_ |
| Đơn vị giá (VND / nghìn VND) | _chưa kiểm tra_ |
| Giá đã điều chỉnh hay chưa | _chưa kiểm tra_ |
| Giới hạn tốc độ quan sát được | _chưa kiểm tra_ |
| Nguồn bên dưới được dùng | _chưa kiểm tra_ |

---

## 3. Kiến trúc

```
                 Thứ 6, 18:00 ICT (11:00 UTC)
                          │
                    ┌─────▼──────┐
                    │  Scheduler │
                    └─────┬──────┘
                          │
              ┌───────────▼────────────┐
              │  Ingestion job         │
              │  DataProvider (vnstock)│
              └───────────┬────────────┘
                          │ ghi nguyên bản
                  ┌───────▼───────┐
                  │  RAW (object  │
                  │   storage)    │
                  └───────┬───────┘
                          │
              ┌───────────▼────────────┐
              │  Validation            │──► quality_issues
              └───────────┬────────────┘
                          │ chỉ mã đạt
              ┌───────────▼────────────┐
              │  CURATED (prices_daily)│
              └───────────┬────────────┘
                          │
              ┌───────────▼────────────┐
              │  Feature computation   │
              │  (features_daily)      │
              └───────────┬────────────┘
                          │ commit nguyên tử + publish run
                          ▼
              Bên đọc (MCP server, xem stock-mcp-tool.md)
```

---

## 4. Pipeline thu thập hàng tuần

### 4.1 Lịch chạy

- Chạy vào Thứ 6, 18:00 ICT, tức 11:00 UTC. Lúc này HOSE đã đóng cửa nên dữ liệu phiên đã chốt.
- Ví dụ cron kiểu EventBridge: `cron(0 11 ? * FRI *)`.
- Không phụ thuộc lịch giao dịch: job lấy dữ liệu đến thời điểm chạy, phiên cuối cùng có dữ liệu là `as_of`. Khi Thứ 6 nghỉ lễ, `as_of` tự nhiên là phiên trước đó.

### 4.2 Danh sách mã (universe)

- Là **file cấu hình do người dùng quản lý** (ví dụ VN100 hoặc watchlist riêng), không lấy động từ API, để tập mã ổn định giữa các tuần.
- Thay đổi danh sách được ghi nhận qua bảng `symbols` (cột `in_universe`).
- **Quyết định còn mở:** D2 (mục 7).

### 4.3 Chiến lược lấy dữ liệu

- Mỗi tuần **lấy lại toàn bộ lịch sử đã điều chỉnh** của mỗi mã, không chỉ nối thêm 5 phiên cuối. Lý do: khi có cổ tức hoặc chia tách, giá quá khứ bị điều chỉnh ngược; nối thêm sẽ gây lệch.
- **Độ sâu lịch sử tối thiểu: 3 năm.** Lý do: trả chỉ báo `SMA200` cho khoảng `1Y` ở phía MCP tool cần ít nhất 200 phiên trước ngày bắt đầu khoảng (khoảng 450 phiên, ~2 năm); dư thêm để có đệm cho mã thiếu phiên.
- Gọi **tuần tự**, nghỉ giữa các lần gọi, thử lại có backoff khi lỗi tạm thời. Lỗi một mã không làm hỏng cả lần chạy.

### 4.4 Interface nguồn dữ liệu

Toàn bộ mã gọi vnstock nằm trong **một adapter duy nhất** triển khai interface `DataProvider`. Phần còn lại của pipeline chỉ làm việc với schema chuẩn của mình.

Hợp đồng của `DataProvider` (mô tả, không phải code):

- Đầu vào: mã, ngày bắt đầu, ngày kết thúc.
- Đầu ra: bảng có các cột chuẩn `symbol, trade_date, open, high, low, close, volume`; giá đơn vị **VND**; giá đã điều chỉnh.
- Adapter chịu trách nhiệm đổi tên cột và đổi đơn vị về chuẩn. Nếu nguồn trả về nghìn VND thì adapter nhân lên.
- Lỗi được báo bằng ngoại lệ có phân loại: tạm thời (thử lại được) hoặc vĩnh viễn (ví dụ mã không tồn tại).

### 4.5 Luồng một lần chạy

1. Tạo `run_id`, ghi bản ghi `runs` với trạng thái `running`.
2. Đọc universe.
3. Với từng mã: lấy dữ liệu, ghi **raw**, ghi nhận kết quả lấy (thành công/lỗi).
4. Chạy **validation** (mục 5) cho từng mã. Mã không đạt bị loại khỏi curated và ghi vào `quality_issues`.
5. Trong **một giao dịch cơ sở dữ liệu**: ghi `prices_daily` (upsert) và tính lại toàn bộ `features_daily` cho các mã đạt.
6. Kiểm tra ngưỡng thất bại của lần chạy (mục 5.3). Nếu đạt, đánh dấu `runs.status = 'published'`; nếu không, `failed`.
7. Gửi thông báo kết quả (mục 4.7).

Bước 5–6 đảm bảo **công bố nguyên tử**: bên đọc chỉ thấy dữ liệu thuộc lần chạy `published` mới nhất.

### 4.6 Tính idempotent

- Chạy lại cùng ngày không tạo bản ghi trùng: `prices_daily` và `features_daily` upsert theo khóa `(symbol, trade_date)`.
- Raw được ghi theo `run_id` nên không ghi đè lần chạy trước.
- Hệ quả chấp nhận được: curated chỉ giữ **phiên bản giá điều chỉnh mới nhất**. Các phiên bản trước nằm trong raw.

### 4.7 Giám sát và thông báo

- Mỗi lần chạy gửi một thông báo tóm tắt: số mã thành công/bị loại/lỗi, `as_of`, các cảnh báo.
- Thất bại (trạng thái `failed`) gửi thông báo mức cao.
- **Kênh thông báo:** chưa chọn (D6).

---

## 5. Kiểm tra chất lượng dữ liệu

### 5.1 Các kiểm tra theo mã

| Mã kiểm tra | Điều kiện | Mức |
|---|---|---|
| `EMPTY` | Không có dòng nào | error |
| `DUPLICATE_DATE` | Trùng `trade_date` | error |
| `NON_POSITIVE_PRICE` | Có giá ≤ 0 | error |
| `HIGH_LT_LOW` | `high < low` | error |
| `CLOSE_OUT_OF_RANGE` | `close` ngoài `[low, high]` | error |
| `NEGATIVE_VOLUME` | `volume < 0` | error |
| `LARGE_DAILY_MOVE` | Biến động giá đóng cửa giữa hai phiên liên tiếp vượt ngưỡng | warn |
| `ZERO_VOLUME_DAYS` | Nhiều phiên khối lượng bằng 0 | warn |
| `SHORT_HISTORY` | Số phiên ít hơn mức cần cho chỉ báo dài nhất | warn |

Ghi chú về `LARGE_DAILY_MOVE`: ngưỡng đề xuất 15% (bằng biên độ lớn nhất của các sàn theo hiểu biết hiện tại: HOSE ±7%, HNX ±10%, UPCoM ±15%; **cần xác minh biên độ hiện hành**, D8). Mức `warn` vì giá chưa điều chỉnh đúng cho sự kiện doanh nghiệp cũng gây ra giá trị này, và cần người xem xét.

### 5.2 Kiểm tra theo lần chạy

| Mã kiểm tra | Điều kiện | Mức |
|---|---|---|
| `STALE_DATA` | Phiên mới nhất cách ngày chạy quá N ngày lịch (đề xuất N = 5) | warn |
| `CROSS_SOURCE_MISMATCH` | Giá đóng cửa lệch nguồn đối chiếu quá ngưỡng trên mẫu ngẫu nhiên (chỉ khi có nguồn thứ hai) | warn |
| `UNIVERSE_COVERAGE` | Tỷ lệ mã thành công thấp | xem 5.3 |

`STALE_DATA` chỉ cảnh báo vì kỳ nghỉ dài (ví dụ Tết) có thể vượt N hợp lệ.

### 5.3 Ngưỡng thất bại

- Mã có ít nhất một kiểm tra `error` bị **loại khỏi curated** trong tuần đó.
- Nếu tỷ lệ mã bị loại hoặc lỗi lấy dữ liệu **vượt 10%** universe, lần chạy là `failed` và **không công bố**. Dữ liệu tuần trước vẫn là phiên bản được phục vụ.
- Mức 10% là đề xuất khởi đầu, điều chỉnh sau khi có dữ liệu vận hành thực tế.

---

## 6. Schema dữ liệu (hợp đồng với MCP tool)

Đây là **giao diện duy nhất** giữa pipeline và MCP tool. Thay đổi schema ở đây phải được phản ánh trong `stock-mcp-tool.md`.

### 6.1 Quy ước chung

- Mọi giá trị tiền tệ: **VND**, không dùng "nghìn VND".
- Ngày giao dịch (`trade_date`): kiểu DATE, theo ngày địa phương Việt Nam (Asia/Ho_Chi_Minh).
- Mã chứng khoán (`symbol`): chữ in hoa, ví dụ `FPT`, không kèm hậu tố sàn.
- Thời điểm (`*_at`): TIMESTAMP có múi giờ (UTC).
- Giá là **giá đã điều chỉnh** (cột `adjusted` luôn là true trong giai đoạn này, giữ để sau mở rộng).

### 6.2 Lớp raw

Lưu dạng tệp trong object storage, **không sửa, không xóa**.

- Đường dẫn gợi ý: `raw/prices/source=<nguồn>/run_date=<YYYY-MM-DD>/run_id=<id>/prices.<định dạng>`
- Nội dung: dữ liệu đúng như nguồn trả về, thêm hai cột `fetched_at` và `run_id`. Không đổi tên cột, không đổi đơn vị ở lớp này.
- Định dạng (Parquet hay CSV nén): D4 (mục 7).

### 6.3 Lớp curated

**`runs`** — mỗi lần chạy một dòng

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `run_id` | text, PK | |
| `started_at`, `finished_at` | timestamptz | |
| `status` | text | `running` / `published` / `failed` |
| `as_of_date` | date | Phiên mới nhất trong lần chạy |
| `provider` | text | Ví dụ `vnstock` |
| `provider_version` | text | Phiên bản thư viện |
| `symbols_total`, `symbols_ok`, `symbols_excluded`, `symbols_failed` | integer | |

**`symbols`** — danh mục mã

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `symbol` | text, PK | |
| `exchange` | text | HOSE / HNX / UPCOM |
| `name` | text | Có thể rỗng |
| `in_universe` | boolean | Có thuộc danh sách theo dõi hiện tại |

**`prices_daily`** — giá hàng ngày

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `symbol` | text | Khóa chính (1/2), tham chiếu `symbols` |
| `trade_date` | date | Khóa chính (2/2) |
| `open`, `high`, `low`, `close` | numeric | VND, > 0 |
| `volume` | bigint | ≥ 0 |
| `adjusted` | boolean | |
| `source` | text | |
| `run_id` | text | Lần chạy ghi/cập nhật gần nhất |

Ràng buộc ở mức cơ sở dữ liệu: `low <= high`, `close BETWEEN low AND high`, giá > 0, `volume >= 0`. Mục đích là chặn dữ liệu sai ngay cả khi lớp validation trong ứng dụng có lỗi.

**`symbol_run_status`** — trạng thái từng mã trong từng lần chạy

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `run_id`, `symbol` | text, PK ghép | |
| `status` | text | `ok` / `excluded` / `failed` |
| `row_count` | integer | |
| `first_date`, `last_date` | date | |

**`quality_issues`**

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `run_id`, `symbol` | text | `symbol` có thể rỗng với kiểm tra mức lần chạy |
| `check_code` | text | Theo mục 5 |
| `severity` | text | `error` / `warn` |
| `detail` | text | Mô tả ngắn, có số liệu |
| `created_at` | timestamptz | |

### 6.4 Lớp features

**`features_daily`** — chỉ báo tính sẵn theo ngày, tính trên toàn bộ lịch sử của mã rồi mới cắt theo khoảng khi truy vấn.

| Cột | Kiểu | Định nghĩa |
|---|---|---|
| `symbol`, `trade_date` | PK ghép | |
| `sma20`, `sma50`, `sma200` | numeric, null được | Trung bình động đơn giản của `close` |
| `ema12`, `ema26` | numeric, null được | Trung bình động hàm mũ của `close` |
| `rsi14` | numeric, null được | RSI 14 phiên |
| `macd`, `macd_signal`, `macd_hist` | numeric, null được | MACD (12, 26, 9) |
| `bb_upper`, `bb_mid`, `bb_lower` | numeric, null được | Bollinger 20 phiên, 2 độ lệch chuẩn |
| `atr14` | numeric, null được | ATR 14 phiên |
| `vol_sma20` | numeric, null được | Trung bình động 20 phiên của `volume` |
| `feature_version` | text | Phiên bản công thức tính |
| `run_id` | text | |

Quy tắc:
- Giá trị là **null** khi chưa đủ số phiên để tính, **không** điền 0 hay tính từ phần dữ liệu thiếu.
- Mọi thay đổi công thức tăng `feature_version` để truy vết được.
- Toàn bộ chỉ báo được tính lại mỗi lần chạy (vì giá điều chỉnh thay đổi quá khứ).

### 6.5 Công bố nguyên tử

Ghi `prices_daily` và `features_daily` trong **một giao dịch**; chỉ sau khi giao dịch thành công và vượt ngưỡng thất bại mới đánh dấu `runs.status = 'published'`. Bên đọc luôn truy vấn dựa trên lần chạy `published` mới nhất.

---

## 7. Các quyết định còn mở (phía pipeline)

| Mã | Câu hỏi | Lựa chọn | Gợi ý | Trạng thái |
|---|---|---|---|---|
| D1 | API, cột và đơn vị giá của vnstock bản hiện tại là gì? | Chạy script probe | Làm đầu tiên (Giai đoạn 0) | Mở |
| D2 | Universe gồm những mã nào? | VN30 / VN100 / watchlist riêng | Bắt đầu nhỏ (VN30 hoặc watchlist), mở rộng sau | Mở |
| D3 | Pipeline chạy ở đâu? | AWS Lambda hoặc ECS / GitHub Actions / máy cá nhân | Chọn theo thời gian chạy sau khi probe; lịch hàng tuần nên rất nhẹ | Mở |
| D4 | Lưu curated ở đâu, raw ở định dạng nào? | Postgres hoặc DuckDB; Parquet hoặc CSV nén | Postgres nếu MCP server chạy từ xa; DuckDB nếu mọi thứ chạy cục bộ | Mở |
| D5 | Có nguồn đối chiếu thứ hai không? | SSI FastConnect / không | Có nếu bạn có hoặc sẵn sàng mở tài khoản SSI; nếu không, bỏ qua giai đoạn đầu | Mở |
| D6 | Kênh thông báo kết quả chạy? | Email / Slack / khác | Chọn kênh bạn kiểm tra hằng ngày | Mở |
| D8 | Biên độ giá các sàn hiện hành (cho ngưỡng cảnh báo biến động ngày) | Xác minh theo quy định hiện hành | Xác minh trước khi hoàn thiện kiểm tra `LARGE_DAILY_MOVE` | Mở |

(D7 liên quan đến MCP server, xem `stock-mcp-tool.md`.)

---

## 8. Lộ trình (phần pipeline)

**Giai đoạn 0 — Xác minh (nhỏ, làm trước)**
- Viết và chạy script probe trên máy có mạng. Điền mục 2.3. Chốt D1.

**Giai đoạn 1 — Pipeline giá**
- Adapter vnstock, raw, validation, `prices_daily`, `runs`, `symbol_run_status`, `quality_issues`.
- Chạy thủ công và kiểm tra bằng mắt trên một số mã.
- Lên lịch hàng tuần và thông báo kết quả.

**Giai đoạn 2 — Chỉ báo và công bố nguyên tử**
- Tính `features_daily`, công bố nguyên tử theo mục 6.5.
- (MCP tool ở giai đoạn này nằm trong `stock-mcp-tool.md`.)

**Giai đoạn 3 — Củng cố**
- Nguồn đối chiếu (nếu D5 có), giám sát, báo cáo chất lượng dữ liệu theo tuần.

**Giai đoạn 4 — Mở rộng**
- Báo cáo tài chính (cần lưu ngày công bố để tránh sai lệch nhìn trước khi backtest).
- Backtest các tín hiệu; ghi lại mọi khuyến nghị của AI để đánh giá sau này.

---

## 9. Rủi ro đã biết

| Rủi ro | Giảm thiểu |
|---|---|
| vnstock thay đổi API hoặc nguồn bên dưới | Cô lập bằng adapter; ghi `provider_version` mỗi lần chạy; kiểm tra chất lượng sẽ bắt dữ liệu bất thường |
| Sai đơn vị giá (nghìn VND so với VND) | Probe ở Giai đoạn 0; adapter chuẩn hóa về VND; ràng buộc và kiểm tra giá bất thường |
| Giá điều chỉnh làm lệch quá khứ | Lấy lại toàn bộ lịch sử mỗi tuần; giữ raw để truy vết |
| Điều khoản sử dụng nguồn dữ liệu | Dùng cá nhân; nếu mở rộng thành sản phẩm hoặc dùng trong tổ chức, xin phép tác giả/nhà cung cấp |
| Run Thứ 6 thất bại mà không ai biết | Thông báo bắt buộc; lần chạy dang dở không được công bố |
| Quá tin tín hiệu từ dữ liệu giá công khai | Backtest nghiêm túc (tránh look-ahead và survivorship bias); xem AI là một đầu vào, không phải quyết định tự động |

---

## 10. Tài liệu tham khảo

- vnstock trên GitHub: https://github.com/thinh-vu/vnstock
- vnstock trên PyPI (bản 3.2.4, đã bị quarantine; có bản mới hơn): https://pypi.org/project/vnstock/3.2.4/
- SSI FastConnect Data: https://guide.ssi.com.vn/ssi-products/fastconnect-data
- Đăng ký SSI Fast Connect API: https://www.ssi.com.vn/en/individual-customer/fast-connect-api
- Tổng quan nguồn dữ liệu tài chính Việt Nam (Tidy Finance VN): https://mikenguyen13.github.io/tidy_finance_vn/01_accessing_and_managing_financial_data.html

> Tài liệu này mô tả thiết kế, không phải tư vấn đầu tư.
