FROM python:3.12-slim

WORKDIR /app

# 复制 MCP server
COPY mcp_server/ ./mcp_server/
COPY requirements.txt ./

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["python", "-m", "mcp_server", "--host", "0.0.0.0", "--port", "8000"]
