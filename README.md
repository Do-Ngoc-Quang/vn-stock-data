# vn-stock-data

Dữ liệu giao dịch cổ phiếu Việt Nam (EOD, cập nhật hàng tuần) cho AI agent truy vấn qua MCP tool.

> Trạng thái: **bản nháp thiết kế, chưa có code.** Không phải tư vấn đầu tư.

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
├── docs/
│   └── design/                 # Tài liệu thiết kế
├── config/                     # Universe (danh sách mã), cấu hình pipeline
├── pipeline/                   # Phía sản xuất dữ liệu
│   ├── providers/              # Adapter DataProvider (vnstock, ...)
│   ├── validation/             # Kiểm tra chất lượng (mục 5)
│   ├── features/               # Tính chỉ báo → features_daily
│   └── db/                     # Truy cập cơ sở dữ liệu, công bố nguyên tử
├── mcp_server/                 # Phía đọc dữ liệu (chỉ SELECT)
│   └── tools/                  # get_price_history, get_data_status
├── sql/                        # Schema, migration
├── scripts/                    # Script probe vnstock (Giai đoạn 0), tiện ích
└── tests/
    ├── pipeline/
    └── mcp_server/
```

Các thư mục rỗng giữ chỗ bằng `.gitkeep`; cấu trúc có thể đổi khi chốt các quyết định mở (D3, D4, D7).
