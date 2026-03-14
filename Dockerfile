FROM node:22-slim

# 安装 Python
RUN apt-get update && apt-get install -y python3 python3-pip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 supergateway
RUN npm install -g supergateway

# 复制 MCP server
COPY mcp_server/ ./mcp_server/
COPY requirements.txt ./

# 安装 Python 依赖
RUN pip3 install --no-cache-dir -r requirements.txt --break-system-packages

EXPOSE 8000

CMD ["supergateway", "--port", "8000", "--stdio", "python3 -m mcp_server"]
