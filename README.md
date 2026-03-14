# Flow2API MCP Server (HTTP)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

将 [Flow2API](https://github.com/TheSmallHanCat/flow2api) / OpenAI-compatible 上游封装为 **MCP 图片生成工具**，支持 **stdio** 和 **HTTP (SSE)** 双传输模式。

> 基于 [flow2api-mcp](https://github.com/Barometer-2002/flow2api-mcp) 重构，升级适配新版 Flow2API，专注图片生成场景。

---

## ✨ 特性

- 🎨 **文生图 / 图生图** — 支持 Gemini 3.1 Flash / 3.0 Pro / Imagen 4.0 等图片模型
- 🔄 **模型自动同步** — 启动时从上游 `/v1/models` 自动拉取最新图片模型列表
- 📦 **本地媒体缓存** — 下载上游临时链接到本地，内置 HTTP 服务提供稳定访问
- 📜 **跨会话历史** — 用稳定 `history_id` 跨会话复用历史图片，支持连续改图
- 🐳 **Docker 一键部署** — 通过 [supergateway](https://github.com/nichochar/supergateway) 桥接 stdio → HTTP SSE
- 🖼️ **用户图片导入** — 读取 Cherry Studio 本地附件，用于图生图参考

---

## 🚀 快速开始

### 方式一：Docker 部署（推荐）

```bash
git clone https://github.com/Barometer-2002/flow2api-mcp-http.git
cd flow2api-mcp-http

# 编辑 docker-compose.yml 中的环境变量后启动
docker compose up -d
docker compose logs -f
```

### 方式二：本地 stdio 模式

适用于 Cherry Studio 等原生支持 stdio MCP 的客户端。

```bash
pip install -r requirements.txt
python -m mcp_server
```

### 方式三：本地 HTTP 模式

适用于 Cursor、Claude Desktop 等通过 HTTP SSE 连接 MCP 的客户端。

```bash
pip install -r requirements.txt
npm install -g supergateway

supergateway --port 8000 --stdio "python -m mcp_server"
```

---

## ⚙️ 配置

所有配置通过 **环境变量** 设置。

### 必填

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FLOW2API_BASE_URL` | 上游 Flow2API 服务地址 | `http://localhost:8000` |
| `FLOW2API_API_KEY` | API Key（不带 `Bearer` 前缀） | — |

### 缓存相关

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FLOW2API_MCP_URL_CACHE` | 启用本地媒体缓存（`1`=开启） | `0` |
| `FLOW2API_MCP_CACHE_HTTP_PORT` | 缓存 HTTP 服务端口 | `46262` |
| `FLOW2API_MCP_EXTERNAL_URL_PREFIX` | Docker/远程部署时，缓存文件的外部访问前缀 | — |
| `FLOW2API_MCP_HOST` | 缓存 HTTP 服务监听地址（Docker 需设为 `0.0.0.0`） | `127.0.0.1` |
| `FLOW2API_MCP_URL_CACHE_MAX_ENTRIES` | 缓存最大条目数 | `200` |
| `FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES` | 单文件最大缓存大小（MB） | `100` |

### 历史 & 其他

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FLOW2API_MCP_IMAGE_DIR` | 用户上传图片缓存目录（兼容旧版名称 `...CHERRYSTUDIO_FILES_DIR`） | — |
| `FLOW2API_MCP_HISTORY_RECENT_SIZE` | 近期历史保留条数 | `50` |
| `FLOW2API_MCP_HISTORY_ARCHIVE_SIZE` | 归档历史保留条数 | `2000` |
| `FLOW2API_MCP_GENERATE_RETRY_COUNT` | 生成失败自动重试次数 | `0` |
| `FLOW2API_MCP_DEBUG` | 调试日志（`1`=开启） | `0` |

---

## 🧰 MCP 工具

本服务提供 3 个 MCP 工具：

### `generate` — 生成图片

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | ✅ | 图片模型名称（从 `models.json` 枚举中选择） |
| `prompt` | string | ✅ | 生成描述（主体/场景/构图/光线/风格/细节） |
| `history_id` | integer | — | **基于历史图片**：传入历史记录的 ID 提取参考图（适合连续改图） |
| `use_latest_user_image` | boolean | — | **基于本地图片**：使用本地配置目录下的最新图片作为参考图 |
| `image_url` | string | — | **基于网络图片**：自动下载外部 URL 图片作为参考图（适合远程部署） |

> **参考图来源三选一**：`history_id`、`use_latest_user_image` 与 `image_url` 互斥，不传则为纯文本生成。

**示例：**
```json
// 文生图
{ "model": "gemini-3.1-flash-image-landscape", "prompt": "一只可爱的猫咪在花园里玩耍" }

// 基于历史图片继续改图
{ "model": "gemini-3.0-pro-image-landscape", "prompt": "把背景改成星空", "history_id": 5 }
```

### `history` — 查看生成历史

| 参数 | 类型 | 说明 |
|------|------|------|
| `scope` | string | `recent`（短期）或 `archive`（长期），默认 `recent` |
| `limit` | integer | 返回条数，默认 5 |
| `history_id` | integer | 查看指定条目 |

### `cache` — 缓存管理

| 参数 | 类型 | 说明 |
|------|------|------|
| `action` | string | `status` 查看 / `clear` 清空 / `prune` 裁剪，默认 `status` |
| `keep` | integer | `prune` 时保留条数，默认 50 |
| `include_history` | boolean | 是否同时清理历史记录 |
| `confirm` | boolean | 删除历史记录需显式确认 |

---

## 📋 支持的图片模型

| 系列 | 模型前缀 | 特点 |
|------|---------|------|
| **Gemini 3.1 Flash** | `gemini-3.1-flash-image-*` | ⚡ 速度快，质量好（推荐默认） |
| **Gemini 3.0 Pro** | `gemini-3.0-pro-image-*` | 🏆 质量最佳 |
| **Gemini 2.5 Flash** | `gemini-2.5-flash-image-*` | ⚡ 速度优先 |
| **Imagen 4.0** | `imagen-4.0-generate-preview-*` | 🎨 独特风格 |

**画幅后缀：** `-landscape`（横屏）`-portrait`（竖屏）`-square`（方图）`-four-three`（4:3）`-three-four`（3:4）

**分辨率后缀：** 无后缀（标准）、`-2k`、`-4k`

> 模型列表在启动时会自动从上游同步，也可手动编辑 `mcp_server/models.json`。

---

## 🏗️ 架构

```
┌──────────────────────────────────────────────┐
│                MCP Client                     │
│  (Cherry Studio / Cursor / Claude Desktop)    │
└────────┬────────────────────────┬────────────┘
         │ stdio                  │ HTTP SSE
         │                        │
    ┌────▼────┐           ┌───────▼────────┐
    │  MCP    │           │  supergateway  │
    │ Server  │           │  (stdio→HTTP)  │
    │ (Python)│           └───────┬────────┘
    └────┬────┘                   │ stdio
         │◄───────────────────────┘
         │
    ┌────▼────────────────────────────────┐
    │         Flow2API Upstream           │
    │  (OpenAI-compatible API Server)     │
    └─────────────────────────────────────┘
```

### 本地缓存 HTTP 服务

开启 `FLOW2API_MCP_URL_CACHE=1` 后，MCP 会把上游返回的临时链接下载到本地 `url_cache/`，并通过内置 HTTP 服务提供稳定访问，避免上游链接过期：

```
http://127.0.0.1:46262/mcp-cache/{hash}.{ext}
```

---

## 🔧 Cherry Studio 配置

| 配置项 | 值 |
|--------|-----|
| 类型 | 标准输入/输出 (stdio) |
| 命令 | Python 解释器路径（如 `python`） |
| 参数 | 项目中 `mcp_server/server.py` 的完整路径 |
| 长时间运行模式 | ✅ 开启 |
| 超时 | 180 秒或更高 |

**环境变量：**
```
FLOW2API_BASE_URL=http://your-flow2api-host:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_IMAGE_DIR=C://Users//<USERNAME>//AppData//Roaming//CherryStudio//Data//Files
```

---

## 🐳 Docker 部署

项目根目录已提供 `docker-compose.yml`，编辑其中的环境变量后直接启动：

```bash
# 修改 FLOW2API_BASE_URL 和 FLOW2API_API_KEY
vim docker-compose.yml

docker compose up -d
```

如需远程访问缓存的图片，需设置 `FLOW2API_MCP_EXTERNAL_URL_PREFIX` 为服务器的外部地址。

---

## 📁 项目结构

```
flow2api-mcp-http/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── mcp_server/
    ├── __init__.py       # 版本号
    ├── __main__.py       # 入口 + 模型自动同步
    ├── config.py         # 配置常量
    ├── utils.py          # URL/MIME 工具函数
    ├── history.py        # 跨会话历史管理
    ├── client.py         # HTTP 客户端 + 流式解析
    ├── cache.py          # 本地缓存 + HTTP 服务
    ├── tools.py          # 工具定义与处理逻辑
    ├── server.py         # MCP 协议注册入口
    └── models.json       # 图片模型配置
```

---

## 📄 License

[MIT License](LICENSE)

## 🙏 致谢

- [Flow2API](https://github.com/TheSmallHanCat/flow2api) — 上游 API 服务
- [supergateway](https://github.com/nichochar/supergateway) — stdio → HTTP SSE 桥接
- [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) — Model Context Protocol Python SDK
