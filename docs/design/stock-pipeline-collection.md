# Thiết kế: Pipeline thu thập dữ liệu giao dịch chứng khoán Việt Nam

- **Tài liệu liên quan:** `stock-mcp-tool.md` (MCP tool để AI agent truy vấn dữ liệu). Hai tài liệu nối với nhau **chỉ qua schema ở mục 6** của tài liệu này.

---

## 1. Mục tiêu và phạm vi

### 1.1 Mục tiêu

Xây dựng một nguồn dữ liệu đáng tin cậy ("nguồn sự thật") về giao dịch cổ phiếu Việt Nam để AI agent truy vấn, phân tích insight và hỗ trợ ra quyết định mua/bán của người dùng. Tài liệu này chỉ nói về **phía sản xuất dữ liệu**: từ nguồn bên ngoài đến các bảng đã làm sạch.

### 1.2 Phạm vi

- Thị trường: Việt Nam (HOSE, HNX, UPCoM).
- Dữ liệu: giá và khối lượng giao dịch hàng ngày (OHLCV), đã điều chỉnh.
- Cập nhật: **người dùng kích hoạt thủ công** bằng một lệnh, khoảng mỗi tuần một lần sau khi thị trường đóng cửa.
- Chỉ báo kỹ thuật tính sẵn (mục 6.4).
- Chạy hoàn toàn cục bộ trên máy cá nhân (mục 3.1).

### 1.3 Ngoài phạm vi

- Dữ liệu trong phiên (intraday) và streaming.
- Đặt lệnh hoặc giao dịch tự động.
- Báo cáo tài chính và dữ liệu vĩ mô.
- Nguồn dữ liệu thứ hai để đối chiếu.
- Backtest tín hiệu.
- Triển khai lên máy chủ hoặc đám mây.

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

Nguồn duy nhất là **vnstock** (Python). Thư viện lấy dữ liệu từ các API công khai của công ty chứng khoán, nên nguồn bên dưới có thể thay đổi; vì vậy mọi lời gọi nằm sau adapter (mục 4.4).

### 2.2 Script probe và kết quả

Script `scripts/probe_vnstock.py` gọi vnstock trên một vài mã và ghi báo cáo vào `data/probe/report.json`. Bản báo cáo lần chạy đầu được lưu ở `docs/probe/vnstock-5.2.2-2026-11-09.json`.

**Kết quả lần 1** (vnstock 5.2.2, chạy 2026-11-09 lúc 15:22 giờ Việt Nam, mã FPT và VCB):

| Mục kiểm tra | Kết quả |
|---|---|
| Phiên bản vnstock | 5.2.2 |
| Cách gọi | `Market().equity(symbol).ohlcv(start, end, interval="1D", source=...)`. Lớp `Vnstock()` và hàm `stock_historical_data` đã bị bỏ |
| Nguồn hỗ trợ `ohlcv` | `vci`, `asean`, `mas`, `kbs`, `vnd`. `tcbs` không hỗ trợ |
| Nguồn đã chạy thành công | `vci` (32 dòng cho khoảng 45 ngày, cả FPT lẫn VCB) |
| Cột trả về | `time, open, high, low, close, volume` |
| Kiểu dữ liệu | `time`: datetime có múi giờ `Asia/Ho_Chi_Minh`; giá: float64; `volume`: int64 |
| Đơn vị giá | Rất có khả năng là **nghìn VND**: `close` FPT 51.0, VCB 53.6; giá có một chữ số thập phân. Chờ xác nhận bằng cách so với bảng giá cùng ngày |
| Giá đã điều chỉnh | Chưa kiểm tra |
| Thời gian phản hồi | Trung vị khoảng 0,07–0,08 giây; lần đầu tới 1,3 giây; 5 lần liên tiếp không lỗi |
| Giới hạn tốc độ | Chưa quan sát được (mới 5 lần gọi) |
| Dòng của ngày chạy | Có dòng 2026-11-09 khi chạy sau 15:00 |

**Còn lại của D1:**
- xác nhận đơn vị giá với bảng giá thực tế;
- kiểm tra giá đã điều chỉnh (hướng dẫn thủ công có trong báo cáo);
- đo giới hạn tốc độ bằng nhiều lần gọi hơn, trên cả universe;
- thử các nguồn khác (`kbs`, `vnd`) để biết nguồn nào ổn định nhất;
- vnstock thế hệ 6: theo README của kho GitHub tác giả (chưa xác minh trực tiếp), các phiên bản trước thế hệ 6 ngừng hoạt động từ 2026-11-10 và thế hệ 6 yêu cầu người dùng dùng khóa của nguồn. Phải chạy lại probe trên thế hệ 6 và xác định có cần khóa không (khóa nếu có đưa vào bằng biến môi trường, không ghi vào repo hay image).

Nếu thế hệ 6 không dùng được như thế hệ 5, nguồn dữ liệu phải chọn lại. Adapter (mục 4.4) giữ cho thay đổi này không lan ra phần còn lại.

---

## 3. Kiến trúc

```
             Người dùng chạy lệnh thủ công
                 (python -m pipeline.run)
                          │
                    ┌─────▼──────┐
                    │  Pipeline  │
                    └─────┬──────┘
                          │
              ┌───────────▼────────────┐
              │  Ingestion job         │
              │  DataProvider (vnstock)│
              └───────────┬────────────┘
                          │ ghi nguyên bản
                  ┌───────▼───────┐
                  │  RAW (tệp     │
                  │  Parquet cục  │
                  │  bộ)          │
                  └───────┬───────┘
                          │
              ┌───────────▼────────────┐
              │  Validation            │──► quality_issues
              └───────────┬────────────┘
                          │ chỉ mã đạt
              ┌───────────▼────────────┐
              │  CURATED (DuckDB)      │
              │  prices_daily          │
              └───────────┬────────────┘
                          │
              ┌───────────▼────────────┐
              │  Feature computation   │
              │  (features_daily)      │
              └───────────┬────────────┘
                          │ công bố nguyên tử: đổi tên tệp DB tạm → tệp DB phục vụ
                          ▼
              Bên đọc (MCP server stdio cục bộ, xem stock-mcp-tool.md)
```

### 3.1 Mô hình triển khai cục bộ

| Thành phần | Cách làm |
|---|---|
| Ngôn ngữ, chạy | Python, một lệnh CLI chạy trọn một lần (ví dụ `python -m pipeline.run`), do người dùng kích hoạt; không có scheduler hay tiến trình nền |
| Raw | Tệp Parquet trong thư mục `data/raw/` |
| Curated + features | Một tệp DuckDB `data/curated.duckdb` |
| Log, tóm tắt | `data/logs/`, `data/last_run.json` |
| Cấu hình | `config/` (universe, ngưỡng); không chứa bí mật |

**Ràng buộc của DuckDB cần tính trước:** một tệp DuckDB không cho tiến trình khác đọc trong lúc một tiến trình đang ghi. Vì vậy pipeline **không ghi thẳng vào tệp đang phục vụ** (xem mục 6.5), và MCP server mở tệp ở chế độ chỉ đọc, mỗi yêu cầu một kết nối ngắn rồi đóng.

### 3.2 Đóng gói bằng Docker

Pipeline và MCP server chạy trong container, dùng **chung một image** (cùng mã, cùng phiên bản DuckDB và vnstock), chỉ khác lệnh khởi chạy.

| Thành phần | Cách chạy | Mount `data/` | Mạng |
|---|---|---|---|
| Pipeline | `docker compose run --rm pipeline`: một container chạy xong rồi thoát | đọc/ghi | ra Internet (gọi vnstock) |
| MCP server | `docker run -i --rm ... mcp-server`, do ứng dụng agent khởi chạy; dùng `-i`, không dùng `-t` để stdio hoạt động | **chỉ đọc** (`:ro`) | không có (`--network none`) |

Quy tắc:
- **Mount cả thư mục `data/`, không mount riêng tệp DB.** Công bố bằng đổi tên tạo inode mới; nếu chỉ mount một tệp, container MCP vẫn giữ tệp cũ. Tệp tạm và tệp phục vụ phải cùng một mount để đổi tên nguyên tử.
- **Docker Desktop (macOS/Windows):** đổi tên nguyên tử và khóa tệp của DuckDB trên bind mount kém tin cậy hơn Linux. Khi gặp vấn đề, dùng named volume (sao lưu `data/` khi đó đi qua `docker cp` hoặc một container phụ).
- Đặt `TZ=Asia/Ho_Chi_Minh`, vì quy tắc bỏ phiên chưa chốt (mục 4.1) phụ thuộc giờ Việt Nam.
- Chạy bằng UID của người dùng trên máy chủ để tệp trong `data/` không thuộc root.
- Ghim phiên bản vnstock trong image; probe (mục 2.2) chạy trong chính image này để kết quả khớp môi trường thật.
- Cấu hình (`config/`) mount chỉ đọc; image không chứa bí mật.

---

## 4. Pipeline thu thập

### 4.1 Kích hoạt

- Người dùng chạy lệnh thủ công, khoảng mỗi tuần một lần sau khi thị trường đóng cửa.
- Không phụ thuộc lịch giao dịch: pipeline lấy dữ liệu đến thời điểm chạy, phiên cuối cùng có dữ liệu là `as_of`. Chạy vào ngày nghỉ thì `as_of` là phiên trước đó.
- Nếu chạy trước 15:00 giờ Việt Nam trong ngày giao dịch, pipeline bỏ phiên của ngày hôm nay vì có thể chưa chốt, và ghi cảnh báo.
- Chạy lại bất cứ lúc nào đều an toàn nhờ tính idempotent (mục 4.6).
- Lệnh chạy in tóm tắt kết quả ra màn hình và trả mã thoát khác 0 khi `failed`.

### 4.2 Danh sách mã (universe)

- Là **file cấu hình do người dùng quản lý** (ví dụ VN100 hoặc watchlist riêng), không lấy động từ API, để tập mã ổn định giữa các tuần.
- Bắt đầu với **VN100**, lưu trong `config/universe.txt` (mẫu: `config/universe.example.txt`).
- Thay đổi danh sách được ghi nhận qua bảng `symbols` (cột `in_universe`).

### 4.3 Chiến lược lấy dữ liệu

- Mỗi lần chạy **lấy lại toàn bộ lịch sử đã điều chỉnh** của mỗi mã, không chỉ nối thêm 5 phiên cuối. Lý do: khi có cổ tức hoặc chia tách, giá quá khứ bị điều chỉnh ngược; nối thêm sẽ gây lệch.
- **Độ sâu lịch sử tối thiểu: 3 năm.** `SMA200` cho khoảng `1Y` ở MCP tool cần khoảng 450 phiên (~2 năm); dư thêm để đệm cho mã thiếu phiên.
- Gọi **tuần tự**, nghỉ giữa các lần gọi, thử lại có backoff khi lỗi tạm thời. Lỗi một mã không làm hỏng cả lần chạy.

### 4.4 Interface nguồn dữ liệu

Toàn bộ mã gọi vnstock nằm trong **một adapter duy nhất** triển khai interface `DataProvider`. Phần còn lại của pipeline chỉ làm việc với schema chuẩn của mình.

Hợp đồng của `DataProvider` (mô tả, không phải code):

- Đầu vào: mã, ngày bắt đầu, ngày kết thúc.
- Đầu ra: bảng có các cột chuẩn `symbol, trade_date, open, high, low, close, volume`; giá đơn vị **VND**; giá đã điều chỉnh.
- Adapter chịu trách nhiệm đổi tên cột và đổi đơn vị về chuẩn. Theo probe (mục 2.2), vnstock 5.2.2 trả cột `time` thay cho `trade_date` và giá theo nghìn VND, nên adapter lấy **ngày theo múi giờ `Asia/Ho_Chi_Minh` của `time`** (không quy đổi sang UTC, tránh lệch một ngày) và nhân giá với 1000.
- Lỗi được báo bằng ngoại lệ có phân loại: tạm thời (thử lại được) hoặc vĩnh viễn (ví dụ mã không tồn tại).

### 4.5 Luồng một lần chạy

1. Tạo `run_id`, ghi nhận lần chạy ở trạng thái `running` vào `data/last_run.json` (chưa đụng tới tệp DB đang phục vụ).
2. Đọc universe.
3. Với từng mã: lấy dữ liệu, ghi **raw**, ghi nhận kết quả lấy (thành công/lỗi).
4. Chạy **validation** (mục 5) cho từng mã. Mã không đạt bị loại khỏi curated và ghi vào `quality_issues`.
5. Sao chép tệp DB đang phục vụ thành **tệp tạm** (`data/curated.staging.duckdb`). Trong **một giao dịch** trên tệp tạm: ghi `prices_daily` (upsert) và tính lại toàn bộ `features_daily` cho các mã đạt.
6. Kiểm tra ngưỡng thất bại của lần chạy (mục 5.3). Nếu đạt: đánh dấu `runs.status = 'published'` trong tệp tạm, rồi **đổi tên tệp tạm thành tệp phục vụ** (thao tác nguyên tử của hệ điều hành). Nếu không đạt: bỏ tệp tạm, ghi lần chạy `failed` (mục 6.5).
7. Gửi thông báo kết quả (mục 4.7).

Bước 5–6 đảm bảo **công bố nguyên tử**: bên đọc chỉ thấy tệp DB cũ hoặc tệp DB mới hoàn chỉnh, không bao giờ thấy trạng thái dở dang.

### 4.6 Tính idempotent

- Chạy lại cùng ngày không tạo bản ghi trùng: `prices_daily` và `features_daily` upsert theo khóa `(symbol, trade_date)`.
- Raw được ghi theo `run_id` nên không ghi đè lần chạy trước.
- Hệ quả chấp nhận được: curated chỉ giữ **phiên bản giá điều chỉnh mới nhất**. Các phiên bản trước nằm trong raw.

### 4.7 Kết quả và độ tươi dữ liệu

- Mỗi lần chạy ghi bản tóm tắt (số mã thành công/bị loại/lỗi, `as_of`, cảnh báo) ra màn hình, `data/last_run.json` và `data/logs/`.
- Vì người dùng tự chạy và theo dõi, không cần kênh thông báo ngoài.
- Việc quên chạy được phát hiện qua `get_data_status` (xem `stock-mcp-tool.md`): kết quả cho biết `as_of` và thời điểm hoàn thành.

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

Ghi chú về `LARGE_DAILY_MOVE`: ngưỡng tạm là 15%, bằng biên độ lớn nhất của các sàn nên không báo sót (xem D8). Mức `warn` vì giá chưa điều chỉnh đúng cho sự kiện doanh nghiệp cũng gây ra giá trị này, và cần người xem xét.

### 5.2 Kiểm tra theo lần chạy

| Mã kiểm tra | Điều kiện | Mức |
|---|---|---|
| `STALE_DATA` | Phiên mới nhất cách ngày chạy quá N ngày lịch (đề xuất N = 5) | warn |
| `UNIVERSE_COVERAGE` | Tỷ lệ mã thành công thấp | xem 5.3 |

`STALE_DATA` chỉ cảnh báo vì kỳ nghỉ dài (ví dụ Tết) có thể vượt N hợp lệ.

### 5.3 Ngưỡng thất bại

- Mã có ít nhất một kiểm tra `error` bị **loại khỏi curated** trong lần chạy đó.
- Nếu tỷ lệ mã bị loại hoặc lỗi lấy dữ liệu **vượt 10%** universe, lần chạy là `failed` và **không công bố**. Dữ liệu của lần chạy `published` trước vẫn được phục vụ.
- Mức 10% là đề xuất khởi đầu, điều chỉnh sau khi có dữ liệu vận hành thực tế.

---

## 6. Schema dữ liệu (hợp đồng với MCP tool)

Đây là **giao diện duy nhất** giữa pipeline và MCP tool. Thay đổi schema ở đây phải được phản ánh trong `stock-mcp-tool.md`.

### 6.1 Quy ước chung

- Mọi giá trị tiền tệ: **VND**, không dùng "nghìn VND".
- Ngày giao dịch (`trade_date`): kiểu DATE, theo ngày địa phương Việt Nam (Asia/Ho_Chi_Minh).
- Mã chứng khoán (`symbol`): chữ in hoa, ví dụ `FPT`, không kèm hậu tố sàn.
- Thời điểm (`*_at`): TIMESTAMP có múi giờ (UTC).
- Giá là **giá đã điều chỉnh** (cột `adjusted` luôn là true).

### 6.2 Lớp raw

Lưu dạng tệp Parquet trong thư mục cục bộ `data/raw/`, **không sửa, không xóa**. Đây là nơi duy nhất giữ các phiên bản giá điều chỉnh cũ nên cần sao lưu (mục 9).

- Đường dẫn: `data/raw/prices/source=<nguồn>/run_date=<YYYY-MM-DD>/run_id=<id>/prices.parquet`
- Nội dung: dữ liệu đúng như nguồn trả về, thêm hai cột `fetched_at` và `run_id`. Không đổi tên cột, không đổi đơn vị ở lớp này.

### 6.3 Lớp curated

Lưu trong tệp DuckDB. Kiểu `numeric` ánh xạ sang `DECIMAL`/`DOUBLE` (chọn khi viết DDL ở `sql/`).

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

Ghi `prices_daily` và `features_daily` trong **một giao dịch trên tệp tạm** (bản sao của tệp đang phục vụ). Chỉ sau khi giao dịch thành công và vượt ngưỡng thất bại mới đánh dấu `runs.status = 'published'` rồi đổi tên tệp tạm thành tệp phục vụ. Bên đọc luôn truy vấn dựa trên lần chạy `published` mới nhất.

**Lần chạy thất bại:** tệp tạm bị bỏ, `prices_daily` và `features_daily` của tệp phục vụ không đổi. Bản ghi `runs`, `symbol_run_status`, `quality_issues` của lần thất bại được ghi vào tệp phục vụ bằng một giao dịch ngắn riêng (thử lại nếu tệp đang bị khóa), và luôn có trong `data/last_run.json`. `get_data_status` dựa vào đó để báo "lần chạy mới nhất thất bại, đang phục vụ dữ liệu của lần `published` trước".

**Windows:** không đổi tên đè lên tệp đang mở được, nên bên đọc phải đóng kết nối sau mỗi yêu cầu và pipeline thử lại có giới hạn khi đổi tên.

---

## 7. Điểm còn mở

| Mã | Nội dung | Cách đóng |
|---|---|---|
| D1 | Xác minh vnstock | **Đã đóng một phần.** Đã biết cách gọi, cột, kiểu, độ trễ (mục 2.2). Còn: xác nhận đơn vị, giá điều chỉnh, giới hạn tốc độ, và thế hệ 6 / yêu cầu khóa |
| D8 | Biên độ giá hiện hành của từng sàn (cho ngưỡng `LARGE_DAILY_MOVE`) | Đối chiếu quy chế của HOSE/HNX. Các nguồn tra cứu cho HOSE ±7%, HNX ±10%, UPCoM ±15% nhưng không thống nhất và không có nguồn chính thức |

---

## 8. Lộ trình (phần pipeline)

Bốn giai đoạn, mỗi giai đoạn có điều kiện hoàn thành. Hoàn thành Giai đoạn 3 là kết thúc lộ trình; việc ngoài danh sách này nằm ngoài phạm vi (mục 1.3).

**Giai đoạn 0 — Xác minh**
- Viết và chạy script probe (mục 2.2), trong image Docker nếu đã có.
- *Hoàn thành khi:* các mục probe đã có kết quả, D1 đóng, biết thời gian chạy VN100 và cách adapter đổi tên cột, đổi đơn vị.

**Giai đoạn 1 — Pipeline giá**
- Adapter vnstock, raw, validation, `prices_daily`, `runs`, `symbol_run_status`, `quality_issues`.
- Lệnh `python -m pipeline.run` in tóm tắt kết quả; `Dockerfile` và `compose.yaml` (mục 3.2).
- *Hoàn thành khi:* chạy được cho cả VN100; mã không đạt bị loại và có bản ghi `quality_issues`; chạy lại không tạo bản ghi trùng; kiểm tra bằng mắt một số mã.

**Giai đoạn 2 — Chỉ báo và công bố nguyên tử**
- Tính `features_daily`, công bố nguyên tử theo mục 6.5. MCP tool ở giai đoạn này: xem `stock-mcp-tool.md`.
- *Hoàn thành khi:* lần chạy `failed` không làm đổi dữ liệu đang phục vụ; chỉ báo khớp với tính độc lập bằng công cụ khác trên một số mã.

**Giai đoạn 3 — Hoàn thiện**
- Sao lưu `data/`, báo cáo chất lượng dữ liệu theo từng lần chạy, đối chiếu biên độ giá (D8).
- *Hoàn thành khi:* khôi phục được `data/` từ bản sao lưu; D8 đóng và ngưỡng `LARGE_DAILY_MOVE` được chốt.

---

## 9. Rủi ro đã biết

| Rủi ro | Giảm thiểu |
|---|---|
| vnstock thay đổi API hoặc nguồn bên dưới | Cô lập bằng adapter; ghi `provider_version` mỗi lần chạy; kiểm tra chất lượng sẽ bắt dữ liệu bất thường |
| Sai đơn vị giá (nghìn VND so với VND) | Probe ở Giai đoạn 0; adapter chuẩn hóa về VND; ràng buộc và kiểm tra giá bất thường |
| Giá điều chỉnh làm lệch quá khứ | Lấy lại toàn bộ lịch sử mỗi lần chạy; giữ raw để truy vết |
| Quên chạy hoặc lần chạy thất bại mà không để ý | `get_data_status` báo `as_of`, thời điểm hoàn thành và trạng thái lần chạy gần nhất; `STALE_DATA`; lần chạy dang dở không được công bố |
| Chạy khi phiên hôm nay chưa chốt | Bỏ phiên của ngày hôm nay nếu chạy trước 15:00 giờ Việt Nam (mục 4.1) |
| Mất hoặc hỏng tệp `data/` (đĩa hỏng, xóa nhầm) | Sao lưu `data/curated.duckdb` và `data/raw/` định kỳ ra ổ khác; curated dựng lại được từ raw nếu raw còn |
