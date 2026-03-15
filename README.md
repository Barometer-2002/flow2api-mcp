# Flow2API MCP Server

把 [Flow2API](https://github.com/TheSmallHanCat/flow2api) / OpenAI-compatible 图片上游封装成 MCP 服务。

当前只支持生图相关能力，不支持视频生成功能。

推荐部署方式只有两种：

- 本机常驻 HTTP：适合 Cherry Studio 和本机客户端，入口通常是 `http://127.0.0.1:8866/mcp`
- Docker / 远程部署：适合自己长期挂着，或从别的设备访问

## 先记 3 个地址

| 用途 | 默认示例 | 说明 |
| --- | --- | --- |
| 上游 API | `http://127.0.0.1:8000` | `FLOW2API_BASE_URL`，给 Flow2API / OpenAI-compatible 上游 |
| MCP HTTP | `http://127.0.0.1:8866/mcp` | 客户端真正要连接的 MCP 地址 |
| 缓存图片 | `http://127.0.0.1:8866/mcp-cache/...` | 返回给客户端的稳定图片地址 |

## 核心能力

- 启动时自动从上游 `/v1/models` 同步模型到 `mcp_server/models.json`
- 提供 `generate`、`history`、`cache` 三个工具
- 可把上游临时图片链接缓存到本地，再通过 HTTP 稳定访问
- 支持 `history_id`、`use_latest_user_image`、`image_url` 三种图生图参考图来源，依次是历史结果、用户上传图、外部 URL。

## 部署差异

最重要的其实只有这 3 条：

- 文生图最简单，所有部署方式都能用
- 基于历史结果继续改图，也就是 `history_id`，所有部署方式都能用
- 基于用户上传图改图，也就是 `use_latest_user_image=true`，只有 MCP 进程能直接读到附件目录时才可用；远程没挂载共享目录时，要先把图片传到图床或其他可访问 URL，再改用 `image_url`

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/Barometer-2002/flow2api-mcp.git
cd flow2api-mcp
python -m pip install -r requirements.txt
```

### 2. 推荐直接写 `.env`

本机启动最省事的方式，是在项目根目录创建一个 `.env`：

```dotenv
FLOW2API_BASE_URL=http://127.0.0.1:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
# FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

已存在的系统环境变量优先级更高，不会被 `.env` 覆盖。

如果你只是临时测试，也可以直接设系统环境变量。PowerShell 不要用 `export`，而要写成：

```powershell
$env:FLOW2API_BASE_URL="http://127.0.0.1:8000"
$env:FLOW2API_API_KEY="your-api-key"
```

常用补充：

| 变量 | 什么时候用 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_URL_CACHE=1` | 推荐开启 | 让返回结果先落到本地缓存，避免直接依赖上游临时 URL |
| `FLOW2API_MCP_IMAGE_DIR` | 要读本地附件时 | 比如 Cherry Studio 附件目录 |
| `FLOW2API_MCP_EXTERNAL_URL_PREFIX` | Docker / 远程部署时 | 把缓存地址改成客户端可访问的外部地址，通常和 MCP HTTP 同主机同端口 |

### 3. 选择一种启动方式

#### 方式 A：本机常驻 HTTP

这是推荐的本机部署方式。先准备好 `.env`，然后启动。上游 API 继续用 `8000`，MCP 与缓存图都走 `8866`：

```bash
python -m mcp_server --host 127.0.0.1 --port 8866
```

MCP 地址：

```text
http://127.0.0.1:8866/mcp
```

缓存图地址：

```text
http://127.0.0.1:8866/mcp-cache/<hash>.jpg
```

#### 方式 B：Docker / 远程部署

`docker compose` 默认会读取项目根目录的 `.env`。如果你本机已经在用这一份 `.env`，Docker 通常不需要再配第二套：

- `FLOW2API_BASE_URL`
- `FLOW2API_API_KEY`
- `FLOW2API_MCP_URL_CACHE`
- `FLOW2API_MCP_IMAGE_DIR`

同机测试时，通常只需要保持或补上：

```dotenv
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://127.0.0.1:8866
```

默认的 `docker-compose.yml` 会直接复用本机版本正在使用的运行时文件：

- `mcp_server/url_cache/`
- `mcp_server/history.json`
- `mcp_server/history_archive.json`

也就是说，本机模式下已经生成过的缓存图，切到 Docker 后默认还能继续访问同一个 `mcp-cache` 链接。

然后启动：

```bash
docker compose up -d --build
```

MCP 地址：

```text
http://<server>:8866/mcp
```

如果客户端和容器不在同一台机器，通常还要加：

```text
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://<server>:8866
```

## 客户端配置

### Cherry Studio

推荐直接连本地 HTTP MCP：

| 配置项 | 建议值 |
| --- | --- |
| 类型 | `Streamable HTTP` 或等价的 HTTP MCP 模式 |
| URL | `http://127.0.0.1:8866/mcp` |
| 超时 | 建议 `180s` 或更高 |

### 其他 HTTP MCP 客户端

直接填 MCP URL：

- 本机常驻 HTTP：`http://127.0.0.1:8866/mcp`
- Docker / 远程部署：`http://<server>:8866/mcp`

如果图片能生成，但客户端里打不开，优先检查：

- 是否开启了 `FLOW2API_MCP_URL_CACHE=1`
- 当前是否确实在跑 `python -m mcp_server --host ... --port ...`
- Docker / 跨机器访问时是否设置了 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

## 下一步

- [部署与客户端配置](docs/DEPLOY.md)
- [参考手册](docs/REFERENCE.md)
- [更新日志](CHANGELOG.md)
