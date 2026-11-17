# vn-stock-data

Dữ liệu giao dịch cổ phiếu Việt Nam (EOD, cập nhật khi người dùng chạy pipeline) cho AI agent truy vấn qua MCP tool.

> Trạng thái: đã triển khai Giai đoạn 1–3 (pipeline, chỉ báo, công bố nguyên tử, MCP server, sao lưu, báo cáo chất lượng). Giai đoạn 0 (probe) chưa chạy lại trên vnstock thế hệ 6; chưa chạy thử với dữ liệu thật (xem mục "Chạy").
>
> Toàn bộ chạy **cục bộ**: chạy tay pipeline Python → DuckDB + Parquet → MCP server stdio, đóng gói bằng Docker. Chưa dùng đám mây.

## Tài liệu thiết kế

| Tài liệu | Nội dung |
|---|---|
| [stock-pipeline-collection.md](docs/design/stock-pipeline-collection.md) | Pipeline thu thập, kiểm tra chất lượng, schema dữ liệu (hợp đồng giữa hai phần) |
| [stock-mcp-tool.md](docs/design/stock-mcp-tool.md) | MCP tool `get_price_history`, `get_data_status` |

Hai tài liệu nối với nhau chỉ qua schema ở mục 6 của tài liệu pipeline.

## Cây thư mục

```
vn-stock-data/
├── README.md
├── Dockerfile                  # Một image dùng chung cho pipeline và MCP server 
├── compose.yaml                # Chạy pipeline 
├── docs/
│   └── design/                 # Tài liệu thiết kế
├── config/                     # Universe (danh sách mã), cấu hình pipeline
├── pipeline/                   # Phía sản xuất dữ liệu
│   ├── providers/              # Adapter DataProvider (vnstock, ...)
│   ├── validation/             # Kiểm tra chất lượng (mục 5)
│   ├── features/               # Tính chỉ báo → features_daily
│   └── db/                     # Truy cập cơ sở dữ liệu, công bố nguyên tử
├── mcp_server/                 # Phía đọc dữ liệu (DuckDB chỉ đọc, stdio)
│   └── tools/                  # get_price_history, get_data_status
├── sql/                        # Schema DuckDB (DDL)
├── scripts/                    # Script probe vnstock (Giai đoạn 0), tiện ích
├── tests/
│   ├── pipeline/
│   └── mcp_server/
└── data/                       # Không đưa vào git (tạo khi chạy)
    ├── raw/                    # Parquet, không sửa không xóa
    ├── curated.duckdb          # Tệp đang phục vụ
    ├── logs/
    └── last_run.json
```

Các thư mục rỗng giữ chỗ bằng `.gitkeep`; cấu trúc có thể đổi khi chốt các quyết định mở (D1, D8).

## Chạy

```bash
pip install -r requirements-dev.txt
python -m pytest                                   # 46 test, không cần mạng
cp config/universe.example.txt config/universe.txt # mỗi dòng: MÃ hoặc "MÃ SÀN" (HOSE/HNX/UPCOM)
python -m pipeline.run                             # thu thập, kiểm tra, tính chỉ báo, công bố
python -m pipeline.backup create --dest backups/   # sao lưu data/curated.duckdb và data/raw/
python -m pipeline.backup restore --archive backups/data-XXXX.tar.gz
python -m mcp_server.server                        # MCP server stdio (STOCK_DB_PATH để đổi đường dẫn DB)
```

Docker: `docker compose run --rm pipeline`; MCP server:
`docker run -i --rm --network none -v "$PWD/data:/app/data:ro" vn-stock-data python -m mcp_server.server`.

Mỗi lần chạy ghi `data/last_run.json`, `data/logs/run-<id>.log` và báo cáo chất lượng `data/logs/report-<id>.md`.
MCP server ghi mỗi yêu cầu một dòng JSON (kèm `size_bytes`, `row_count`) ra stderr, hoặc ra tệp `MCP_LOG_FILE` nếu đặt.

## Chưa kiểm chứng

- Nguồn mặc định là CafeF (`config/pipeline.json`, không cần khóa; endpoint nội bộ, có thể đổi). Đã chạy thật 2 mã FPT, VCB (2 năm); chưa chạy VN100, chưa build image Docker. vnstock không còn là mặc định (5.2.2 không cài được từ PyPI, thế hệ 6 cần khóa).
- Hệ số điều chỉnh `GiaDieuChinh/GiaDongCua` của CafeF chưa đối chiếu với ngày không hưởng quyền thực tế.
- Giai đoạn 0 (D1): đối chiếu 5 ngày đổi mức giá với ngày không hưởng quyền, thưởng/chia tách lớn, vnstock thế hệ 6 và khóa nguồn.
- D8: ngưỡng `LARGE_DAILY_MOVE` (HOSE 7%, HNX 10%, UPCoM 15%) đặt theo biên độ thông thường của từng sàn, chưa đối chiếu với văn bản quy chế hiện hành.
- Giới hạn 10 mã / 3.000 dòng của MCP chưa được chỉnh theo kích thước đo trên dữ liệu thật; log `size_bytes` có sẵn để làm việc này.
