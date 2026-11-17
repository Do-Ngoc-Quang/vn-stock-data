# Một image dùng chung cho pipeline và MCP server (thiết kế mục 3.2)
FROM python:3.13-slim
ENV TZ=Asia/Ho_Chi_Minh PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data STOCK_DB_PATH=/app/data/curated.duckdb \
    UNIVERSE_FILE=/app/config/universe.txt PIPELINE_CONFIG=/app/config/pipeline.json
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pipeline ./pipeline
COPY mcp_server ./mcp_server
COPY sql ./sql
# Mặc định chạy pipeline; MCP server: docker run -i --rm --network none -v ./data:/app/data:ro IMAGE python -m mcp_server.server
CMD ["python", "-m", "pipeline.run"]
