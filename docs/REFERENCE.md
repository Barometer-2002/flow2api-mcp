# 参考手册

这份文档合并了高级配置、工具说明和故障排查，适合在已经跑通基本流程之后查细节。

## 高级配置

### 配置规则

- 所有配置都通过环境变量传入
- `FLOW2API_BASE_URL` 填服务根地址，不要自己拼 `/v1`
- `FLOW2API_API_KEY` 直接填 token，不要加 `Bearer `
- 本地图片目录优先级如下：

```text
FLOW2API_MCP_IMAGE_DIR
> FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR
> FLOW2API_MCP_LOCAL_FILES_ROOT
```

### 上游连接

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_BASE_URL` | `http://localhost:8000` | 上游根地址。代码会基于它访问 `/v1/models` 和 `/v1/chat/completions` |
| `FLOW2API_API_KEY` | 空 | 上游 API Key |

### 图片缓存 HTTP 服务

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_URL_CACHE` | `0` | 是否启用本地图片缓存。`1` 为开启 |
| `FLOW2API_MCP_CACHE_HTTP_PORT` | `46262` | 缓存 HTTP 服务端口；被占用时会回退到随机空闲端口 |
| `FLOW2API_MCP_HOST` | `127.0.0.1` | 缓存 HTTP 服务监听地址。Docker / 远程部署通常改成 `0.0.0.0` |
| `FLOW2API_MCP_EXTERNAL_URL_PREFIX` | 空 | 把缓存图片 URL 改写成外部可访问地址 |
| `FLOW2API_MCP_URL_CACHE_MAX_ENTRIES` | `200` | 最多保留的缓存条目数量 |
| `FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES` | `100` | 单个文件最大缓存体积，单位 MB |

推荐开启缓存的场景：

- 远程部署
- Docker 部署
- 客户端经常拿不到上游临时链接
- 你想长期复用 `history_id`

缓存文件默认位于：

- `mcp_server/url_cache/`
- `mcp_server/url_cache.json`

### 本地图片导入

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_IMAGE_DIR` | 空 | 当前推荐的本地图片目录配置 |
| `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR` | 空 | 兼容旧版别名 |
| `FLOW2API_MCP_LOCAL_FILES_ROOT` | 空 | 更老的兼容别名 |

注意：

- MCP 只能读取自己所在机器可访问的目录
- Docker 场景下如果不挂载目录，容器看不到宿主机本地附件
- 只会读取常见图片扩展名：`png`、`jpg`、`jpeg`、`webp`、`gif`、`bmp`、`tif`、`tiff`

### 历史、重试与调试

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_HISTORY_RECENT_SIZE` | `50` | recent 历史保留条数 |
| `FLOW2API_MCP_HISTORY_ARCHIVE_SIZE` | `2000` | archive 历史保留条数 |
| `FLOW2API_MCP_GENERATE_RETRY_COUNT` | `0` | `generate` 失败后的自动重试次数 |
| `FLOW2API_MCP_DEBUG` | `0` | 设为 `1` 后输出调试日志到 stderr |

历史文件默认位于：

- `mcp_server/history.json`
- `mcp_server/history_archive.json`

### 配置相关行为

- 服务启动时会尝试从 `<FLOW2API_BASE_URL>/v1/models` 同步图片模型到 `mcp_server/models.json`
- 如果模型同步失败，服务仍会启动，并回退到已有配置或内置默认模型
- 缓存服务返回地址优先使用 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`，否则使用 `http://127.0.0.1:<实际端口>`

### 实用配置示例

本机 Cherry Studio：

```text
FLOW2API_BASE_URL=http://127.0.0.1:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

Docker / 远程部署：

```text
FLOW2API_BASE_URL=http://host.docker.internal:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_HOST=0.0.0.0
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://your-server:46262
```

调试时：

```text
FLOW2API_MCP_DEBUG=1
FLOW2API_MCP_GENERATE_RETRY_COUNT=1
```

## 工具与内建 Prompt

### 部署方式与功能限制

这部分非常关键：

| 功能 | 本地 `stdio` | 本地 Streamable HTTP | Docker / 远程部署 |
| --- | --- | --- | --- |
| 文生图 | 可用 | 可用 | 可用 |
| `history_id` 改图 | 可用 | 可用 | 可用 |
| `use_latest_user_image` 改图 | 可用 | 可用，但 MCP 必须读得到本地附件目录 | 只有挂载 / 共享附件目录时可用 |
| `image_url` 改图 | 可用 | 可用 | 可用 |

结论：

- 文生图在所有部署方式下都能用
- 基于历史图的改图在所有部署方式下都能用
- 基于用户上传图的改图，只有在 MCP 进程能直接访问附件目录时才可用
- 如果是远程部署且没有共享目录，就需要先把图片传到图床、对象存储或其他可访问 URL，再用 `image_url`

### 工具概览

| 工具 | 用途 |
| --- | --- |
| `generate` | 生成图片，或基于历史 / 本地图片 / 外部图片继续改图 |
| `history` | 查看 recent / archive 历史，找到可复用的 `history_id` |
| `cache` | 查看、裁剪或清理本地缓存与历史记录 |

### `generate`

必填参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `model` | `string` | 模型名，必须在当前支持列表中 |
| `prompt` | `string` | 生成提示词 |

参考图来源三选一：

| 参数 | 类型 | 用途 |
| --- | --- | --- |
| `history_id` | `integer` | 基于历史图片继续改图 |
| `use_latest_user_image` | `boolean` | 使用本地目录中的最新图片做参考图 |
| `image_url` | `string` | 使用远程可访问图片 URL 做参考图 |

如果配置了 `FLOW2API_MCP_IMAGE_DIR`，还可以带：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `user_image_count` | `integer` | 读取最近几张本地图片，默认 `1`，最大 `5` |

建议：

- “继续把上一张改一下” -> `history_id`
- “我刚上传了一张本地图，照着改” -> 只有 MCP 进程能访问该目录时才用 `use_latest_user_image=true`
- “参考公网图片继续画” -> `image_url`

部署限制：

- `history_id` 不依赖本地文件目录，最适合跨机器、远程和长期使用
- `use_latest_user_image=true` 依赖本地目录访问能力，不是“所有部署方式下天然都能传文件”
- 当前 MCP 不支持把客户端本地上传文件直接透传到远程服务；远程场景通常要先把图片放到图床或其他可访问 URL，再走 `image_url`

示例：

```json
{
  "model": "gemini-3.1-flash-image-landscape",
  "prompt": "一只橘猫坐在雨后的霓虹街道边，电影感构图，浅景深，反射高光"
}
```

```json
{
  "history_id": 12,
  "model": "gemini-3.0-pro-image-landscape",
  "prompt": "保持主体不变，把背景改成黄昏海边，色调更柔和"
}
```

```json
{
  "image_url": "https://example.com/reference.png",
  "model": "gemini-3.1-flash-image-landscape",
  "prompt": "保留主体轮廓，改成赛博朋克夜景"
}
```

### `history`

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `scope` | `string` | `recent` | `recent` 或 `archive` |
| `limit` | `integer` | `5` | 返回条数 |
| `history_id` | `integer` | - | 指定时只查看某一条 |

示例：

```json
{
  "scope": "recent",
  "limit": 10
}
```

```json
{
  "history_id": 42
}
```

### `cache`

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `action` | `string` | `status` | `status` / `clear` / `prune` |
| `keep` | `integer` | `50` | `prune` 时保留的条数 |
| `include_history` | `boolean` | `false` | 是否同时处理历史记录 |
| `confirm` | `boolean` | `false` | 删除历史记录时必须显式确认 |

示例：

```json
{
  "action": "status"
}
```

```json
{
  "action": "clear",
  "include_history": true,
  "confirm": true
}
```

### 内建 prompts

| Prompt 名称 | 用途 |
| --- | --- |
| `flow2api_reference_sop` | 参考图选择 SOP |
| `flow2api_prompt_builder` | 把用户需求整理成适合图片模型的单段 prompt |
| `flow2api_troubleshoot_generate` | 生成失败时的最小排查清单 |

## 故障排查

先看这 5 项：

1. `FLOW2API_BASE_URL` 是不是服务根地址，而不是手动拼了 `/v1`
2. `FLOW2API_API_KEY` 是否正确且对目标模型有权限
3. 客户端连接的是不是正确的 MCP 入口，例如 `http://host:8866/mcp`
4. 远程 / Docker 部署是否开启了 `FLOW2API_MCP_URL_CACHE=1`
5. 远程 / Docker 部署是否设置了 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

### 服务能启动，但模型同步失败

通常是：

- 上游不可达
- API Key 无权限访问 `/v1/models`
- `FLOW2API_BASE_URL` 配错了

这不会阻止 MCP 启动。服务会继续使用已有的 `mcp_server/models.json` 或内置默认模型。

### 客户端连不上 MCP

`stdio` 场景优先检查：

- 命令是不是 `python -m mcp_server`
- Python 是否装好了依赖
- 客户端是否把仓库根目录设成工作目录
- 如果不能设工作目录，是否补了 `PYTHONPATH=/path/to/flow2api-mcp`

HTTP 场景优先检查：

- `supergateway` 是否真的在运行
- 客户端连的是不是 `/mcp`
- Docker 场景端口 `8866` 是否映射成功

### 图片生成成功了，但客户端里打不开

通常是链接过期或客户端根本访问不到返回的缓存地址。

建议顺序：

1. 开启 `FLOW2API_MCP_URL_CACHE=1`
2. Docker / 远程部署时设置 `FLOW2API_MCP_HOST=0.0.0.0`
3. 跨机器访问时设置 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

### `use_latest_user_image=true` 找不到本地图片

优先检查：

- 是否设置了 `FLOW2API_MCP_IMAGE_DIR`
- 目录是否存在且有图片文件
- MCP 进程是否真的能访问这个目录

如果是远程容器或跨机器部署，优先改用：

- `history_id`
- `image_url`

本质原因通常不是参数本身有问题，而是远程服务根本拿不到客户端那台机器上的本地文件。这个场景要么挂载 / 共享目录，要么改成先上传图片再传 URL。

### `generate` 返回 empty content 或没有图

常见原因：

- 上游虽然返回了 `200`，但正文其实是拦截、限流或权限错误文案
- 模型名不在当前支持列表里
- 参考图不可用

建议：

1. 临时打开 `FLOW2API_MCP_DEBUG=1`
2. 重跑请求
3. 看 stderr 里上游到底返回了什么

### 常见上游错误

- `401 Unauthorized`：API Key 错了或缺失
- `403 Forbidden`：当前 Key 没权限，或额度 / 风控有问题
- `404 Not Found`：大概率是 `FLOW2API_BASE_URL` 填错了，尤其是多写了路径

## 相关文档

- [README](../README.md)
- [部署与客户端配置](DEPLOY.md)
