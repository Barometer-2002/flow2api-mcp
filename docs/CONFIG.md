# 配置指南

本页涵盖：环境变量、缓存、Cherry Studio 上传目录、模型列表文件。

## 环境变量

| 变量名 | 默认值 | 作用 |
| --- | --- | --- |
| `FLOW2API_BASE_URL` | `http://localhost:8000` | Flow2API 服务地址 |
| `FLOW2API_API_KEY` | 空 | Flow2API API Key |
| `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR` | 空 | Cherry Studio 用户上传目录；不设置则关闭用户上传图导入 |
| `FLOW2API_MCP_URL_CACHE` | `0` | 是否启用本机媒体缓存（写入 `mcp_server/url_cache/` 与 `mcp_server/url_cache.json`） |
| `FLOW2API_MCP_CACHE_HTTP_PORT` | `46262` | 本机缓存 HTTP 端口（端口被占用会回退随机端口；设为 `0` 强制随机） |
| `FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES` | `100` | 单文件缓存上限（单位 MB） |
| `FLOW2API_MCP_URL_CACHE_MAX_ENTRIES` | `200` | URL 缓存最大条目数（超出会按时间淘汰） |
| `FLOW2API_MCP_GENERATE_RETRY_COUNT` | `3` | `generate` 失败自动重试次数（同一模型，每次间隔 2 秒；最大 10；解析为空时不会重试） |
| `FLOW2API_MCP_HISTORY_RECENT_SIZE` | `50` | 短期历史 `mcp_server/history.json` 最大条数 |
| `FLOW2API_MCP_HISTORY_ARCHIVE_SIZE` | `2000` | 长期历史 `mcp_server/history_archive.json` 最大条数 |

说明：
- 所有开关类环境变量：`0` 关闭，其他值开启。

## 本机媒体缓存（推荐）

开启：
- `FLOW2API_MCP_URL_CACHE=1`

常用可调项：
- `FLOW2API_MCP_CACHE_HTTP_PORT=46262`（端口被占用会自动回退随机端口；设为 `0` 强制随机）
- `FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES=100`（单位 MB；例如 `100`=100MB）
- `FLOW2API_MCP_URL_CACHE_MAX_ENTRIES=200`

## Cherry Studio 用户上传图参考（推荐）

由于 MCP 无法直接获取对话中的“附件图片”，本项目通过读取 Cherry Studio 的本地上传目录，实现用户参考图的“上传→复用”。

启用：
- 设置 `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR` 为上传目录（示例：`C:\\Users\\<YOU>\\AppData\\Roaming\\CherryStudio\\Data\\Files`）

支持格式：`png/jpg/jpeg/webp/gif/bmp/tif/tiff`

## 模型列表与选型指南（`mcp_server/models.json`）

默认从 `mcp_server/models.json` 读取配置：
- `models`：可用模型列表（也用于 `generate.model` 的枚举校验）
- `default_model`：默认模型（如果不在 `models` 里会回退到 `models[0]`）
- `selection_guide_lines`：选型指南（按行写，程序会自动用换行拼接）

修改 `mcp_server/models.json` 后需重启 MCP 生效。

