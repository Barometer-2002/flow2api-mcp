# 参考手册

这份文档只放高级配置、工具参数和排障。

## 先记 3 个地址

- `FLOW2API_BASE_URL=http://127.0.0.1:8000`：上游 API
- `http://127.0.0.1:8866/mcp`：推荐的本地 MCP HTTP 地址
- `http://127.0.0.1:8866/mcp-cache/...`：缓存图片地址

## 环境变量

支持自动读取 `.env`：

- 默认先找当前工作目录下的 `.env`
- 如果没找到，再找仓库根目录 `.env`
- 已存在的系统环境变量不会被 `.env` 覆盖
- 如果要指定别的文件路径，可以设置 `FLOW2API_MCP_ENV_FILE`

### 上游连接

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_BASE_URL` | `http://localhost:8000` | 上游根地址。代码会基于它访问 `/v1/models` 和 `/v1/chat/completions` |
| `FLOW2API_API_KEY` | 空 | 上游 API Key |

### 缓存 HTTP

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_URL_CACHE` | `0` | 是否启用本地图片缓存。`1` 为开启 |
| `FLOW2API_MCP_EXTERNAL_URL_PREFIX` | 空 | 把缓存图片 URL 改写成客户端真正可访问的外部地址；原生 HTTP 模式通常设成 `http://<host>:<mcp-port>` |
| `FLOW2API_MCP_URL_CACHE_MAX_ENTRIES` | `200` | 最多保留的缓存条目数量 |
| `FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES` | `100` | 单个文件最大缓存体积，单位 MB |

缓存默认文件：

- `mcp_server/url_cache/`
- `mcp_server/url_cache.json`

默认 `docker-compose.yml` 也会挂载同一份 `mcp_server/url_cache/`，所以本机与 Docker 共享缓存文件。

### 本地图片导入

本地目录优先级：

```text
FLOW2API_MCP_IMAGE_DIR
> FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR
> FLOW2API_MCP_LOCAL_FILES_ROOT
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_IMAGE_DIR` | 空 | 当前推荐的本地图片目录配置 |
| `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR` | 空 | 兼容旧版别名 |
| `FLOW2API_MCP_LOCAL_FILES_ROOT` | 空 | 更老的兼容别名 |

注意：

- MCP 只能读取自己所在机器可访问的目录
- Docker 不挂载目录时，容器看不到宿主机本地附件
- 只会读取常见图片扩展名：`png`、`jpg`、`jpeg`、`webp`、`gif`、`bmp`、`tif`、`tiff`

### 历史、重试与调试

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOW2API_MCP_HISTORY_RECENT_SIZE` | `50` | recent 历史保留条数 |
| `FLOW2API_MCP_HISTORY_ARCHIVE_SIZE` | `2000` | archive 历史保留条数 |
| `FLOW2API_MCP_GENERATE_RETRY_COUNT` | `0` | `generate` 失败后的自动重试次数 |
| `FLOW2API_MCP_PROMPT_SUFFIX` | 内置中文可见文字规则 | 追加到每次 `generate.prompt` 末尾的后缀；设为空字符串可关闭 |
| `FLOW2API_MCP_DEBUG` | `0` | 设为 `1` 后输出调试日志到 stderr |

历史默认文件：

- `mcp_server/history.json`
- `mcp_server/history_archive.json`

默认 `docker-compose.yml` 也会挂载这两个文件，所以本机与 Docker 共享同一份历史记录。

## 常用配置示例

本机 HTTP：

```text
FLOW2API_BASE_URL=http://127.0.0.1:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

Docker / 远程部署：

```text
FLOW2API_BASE_URL=http://192.168.2.125:18000
FLOW2API_API_KEY=han1234
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_IMAGE_DIR=C://Users//Barometer//AppData//Roaming//CherryStudio//Data//Files
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://127.0.0.1:8866
```

补充：

- `docker compose` 默认直接读取项目根目录 `.env`
- 同机测试时，`FLOW2API_BASE_URL` 可以继续用你本机已经验证通过的地址
- 远程部署时，再把 `FLOW2API_MCP_EXTERNAL_URL_PREFIX` 改成外部真实访问地址

调试：

```text
FLOW2API_MCP_DEBUG=1
FLOW2API_MCP_GENERATE_RETRY_COUNT=1
```

自定义提示词后缀：

```text
FLOW2API_MCP_PROMPT_SUFFIX=【默认规则】画面里的所有文字统一使用英文。
```

补充：

- 这个值会原样追加到 `prompt` 末尾
- 如果你需要前导换行或分隔符，也要一并写进去
- 修改后需要重启 MCP 服务

## 工具

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

自动追加规则：

- 默认会在 `prompt` 末尾追加这一段：

```text
【默认规则】画面/字幕/标牌/海报/界面等任何可见文字默认使用简体中文；除非我在提示词里明确指定其他语言或多语言。
```

- 这条规则只影响图片里的可见文字语言
- 如果你在 prompt 里明确要求英文、日文或多语言，以你的显式要求为准
- 如果要改掉这条默认规则，设置 `FLOW2API_MCP_PROMPT_SUFFIX`
- 如果要完全关闭自动追加，把 `FLOW2API_MCP_PROMPT_SUFFIX` 设为空字符串

参考图怎么选：

- 继续改上一张：优先用 `history_id`
- 本机客户端刚上传了新图，且 MCP 真能访问附件目录：用 `use_latest_user_image=true`
- 远程部署或自动化流程：优先用 `image_url`

部署限制：

- `history_id` 不依赖本地文件目录，最稳
- `use_latest_user_image=true` 依赖本地目录访问能力
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

### `cache`

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `action` | `string` | `status` | `status` / `clear` / `prune` |
| `keep` | `integer` | `50` | `prune` 时保留的条数 |
| `include_history` | `boolean` | `false` | 是否同时处理历史记录 |
| `confirm` | `boolean` | `false` | 删除历史记录时必须显式确认 |

### 内建 prompts

| Prompt 名称 | 用途 |
| --- | --- |
| `flow2api_reference_sop` | 参考图选择 SOP |
| `flow2api_prompt_builder` | 把用户需求整理成适合图片模型的单段 prompt |
| `flow2api_troubleshoot_generate` | 生成失败时的最小排查清单 |

## 排障

先看这 5 项：

1. `FLOW2API_BASE_URL` 是不是根地址，而不是手动拼了 `/v1`
2. `FLOW2API_API_KEY` 是否正确且对目标模型有权限
3. 客户端连接的是不是正确的 MCP 地址，例如 `http://127.0.0.1:8866/mcp`
4. 远程 / Docker 部署是否开启了 `FLOW2API_MCP_URL_CACHE=1`
5. 远程 / Docker 部署是否设置了 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

### 模型同步失败

常见原因：

- 上游不可达
- API Key 无权限访问 `/v1/models`
- `FLOW2API_BASE_URL` 配错

这不会阻止 MCP 启动。服务会继续使用已有的 `mcp_server/models.json` 或内置默认模型。

### 客户端连不上 MCP

HTTP 场景优先检查：

- 当前服务是否真的用 `python -m mcp_server --host ... --port ...` 启动
- 客户端连的是不是 `/mcp`
- 本机 `8866` 端口是否被占用
- Docker 场景端口 `8866` 是否映射成功

### 图片生成成功，但客户端里打不开

通常是客户端访问不到返回的缓存地址。

建议顺序：

1. 开启 `FLOW2API_MCP_URL_CACHE=1`
2. 优先使用原生 HTTP 启动
3. 跨机器访问时设置 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

如果你看到的是“上游其实出了图，但客户端里的 URL 很快挂掉”，问题通常不在模型生成，而在缓存地址对客户端不可达。

### `use_latest_user_image=true` 找不到本地图片

优先检查：

- 是否设置了 `FLOW2API_MCP_IMAGE_DIR`
- 目录是否存在且有图片文件
- MCP 进程是否真的能访问这个目录

如果是远程容器或跨机器部署，优先改用：

- `history_id`
- `image_url`

### `generate` 返回 empty content 或没有图

常见原因：

- 上游虽然返回了 `200`，但正文其实是拦截、限流或权限错误文案
- 模型名不在当前支持列表里
- 参考图不可用

建议：

1. 临时打开 `FLOW2API_MCP_DEBUG=1`
2. 重跑请求
3. 看 stderr 里上游到底返回了什么

## 相关文档

- [README](../README.md)
- [部署与客户端配置](DEPLOY.md)
