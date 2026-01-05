# Flow2API MCP Server

一个 stdio MCP 服务：把 Flow2API 的 `/v1/chat/completions` 封装成 MCP 工具，支持图片/视频生成、历史复用、以及本机缓存以对抗公链不稳定。

## 功能
- `generate`：调用 Flow2API 生成图片或视频（流式），把 `reasoning_content` 聚合为“思考/日志”，把 `content` 作为正文返回
- `history`：查看历史（`recent` 短期 / `archive` 长期）
- `cache`：查看/清空/裁剪本机缓存与历史（例如只保留最近 50 条）
- 缓存优先展示：已缓存的媒体 URL 会被替换为本机地址 `http://127.0.0.1:<port>/mcp-cache/...`
- 基于历史继续生成：通过 `history_index` 复用历史里的“图片”结果作为参考图（不支持视频作为参考输入）

## 安装
```bash
pip install -r requirements.txt
```

## 环境变量
说明：
- 所有开关类环境变量：设置为 `0` 表示关闭；其他值表示开启（默认开启）
- `*_BYTES` 单位是字节（bytes）；PowerShell 可用 `200MB` 这类写法

| 变量名 | 必需 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `FLOW2API_BASE_URL` | 是 | `http://localhost:8000` | Flow2API 服务地址 |
| `FLOW2API_API_KEY` | 是 | 空 | Flow2API API Key（不要带 `Bearer ` 前缀） |
| `FLOW2API_MCP_URL_CACHE` | 否 | `1` | 是否启用本机媒体缓存（写入 `mcp_server/url_cache/` 与 `mcp_server/url_cache.json`） |
| `FLOW2API_MCP_URL_CACHE_MAX_ENTRIES` | 否 | `200` | URL 缓存最大条目数（超出会按时间淘汰） |
| `FLOW2API_MCP_URL_CACHE_MAX_FILE_BYTES` | 否 | `26214400`（25MB） | 单个媒体文件允许缓存的最大大小（bytes）；想缓存视频建议调大 |
| `FLOW2API_MCP_HISTORY_MEDIA_CACHE` | 否 | `1` | 是否在 `generate` 成功后，自动预缓存本次返回的部分媒体 URL |
| `FLOW2API_MCP_HISTORY_MEDIA_CACHE_MAX_URLS` | 否 | `6` | 自动预缓存的 URL 数量上限（取返回 URL 的前 N 个） |
| `FLOW2API_MCP_HISTORY_MEDIA_CACHE_TIMEOUT_SECS` | 否 | `20` | 自动预缓存单个 URL 的超时（秒） |
| `FLOW2API_MCP_CACHE_FIRST_RENDERING` | 否 | `1` | 是否把已缓存的媒体 URL 优先替换成本机地址 `http://127.0.0.1:<port>/mcp-cache/...` |
| `FLOW2API_MCP_HISTORY_RECENT_SIZE` | 否 | `50` | 短期历史 `mcp_server/history.json` 最大条数 |
| `FLOW2API_MCP_HISTORY_ARCHIVE_SIZE` | 否 | `2000` | 长期历史 `mcp_server/history_archive.json` 最大条数 |
| `FLOW2API_MCP_GENERATE_MODEL_RETRY_COUNT` | 否 | `3` | `generate` 失败时自动“换模型重试”的次数（0=不重试；最大建议 5） |


## MCP 客户端配置（通用）
关键点：
- `cwd` 指向本仓库根目录（`.../flow2api-mcp`）
- 使用 `python -m mcp_server` 启动
- 在 `env` 里配置 `FLOW2API_BASE_URL` / `FLOW2API_API_KEY`

```json
{
  "mcpServers": {
    "flow2api": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/ABS/PATH/TO/flow2api-mcp",
      "env": {
        "FLOW2API_BASE_URL": "http://127.0.0.1:8000",
        "FLOW2API_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Cherry Studio 配置指南（通用）
Cherry Studio 的 MCP 配置支持“JSON 方式”（类似截图里的 `mcpServers`），也支持表单方式。两种方式本质等价，选你习惯的即可。

注意：
- 这是 **纯 JSON**：不能包含 `//` 注释、不能有多余逗号
- Windows 路径请用 `\\`（例如 `D:\\github\\flow2api-mcp\\mcp_server\\server.py`）

### 方式 A：JSON（stdio）
如果你的 Cherry Studio 配置页面是“示例 JSON (stdio)”那种输入框，直接粘贴下面模板并替换占位符：

#### 无 `cwd` 字段（最兼容，推荐）
适用于：界面只支持 `command` / `args` / `env`，没有 `cwd`。

```json
{
  "mcpServers": {
    "flow2api": {
      "command": "C:\\ABS\\PATH\\TO\\python.exe",
      "args": ["D:\\ABS\\PATH\\TO\\flow2api-mcp\\mcp_server\\server.py"],
      "env": {
        "FLOW2API_BASE_URL": "http://127.0.0.1:8000",
        "FLOW2API_API_KEY": "your-api-key"
      }
    }
  }
}
```

### 方式 B：表单（stdio）
“类型 / 命令 / 参数 / 环境变量”的表单页面：
- 类型：`标准输入/输出 (stdio)`
- 命令：你的 Python 解释器路径（示例：`C:\ABS\PATH\TO\python.exe`）
- 参数（二选一）：
  - 推荐：`-m`、`mcp_server`（若表单支持设置 `cwd`，则把 `cwd` 设为仓库根目录）
  - 兼容：`D:\ABS\PATH\TO\flow2api-mcp\mcp_server\server.py`
- 环境变量（最小必配）：
  - `FLOW2API_BASE_URL`：例如 `http://127.0.0.1:8000`
  - `FLOW2API_API_KEY`：你的 key

## 推荐系统提示词（增强工具调用）
把下面内容粘贴到你的客户端“系统提示词 / System Prompt”里，可显著提高对 MCP 工具的主动调用与回贴结果的一致性：

```text
你已接入 MCP 服务 flow2api（提供 generate/history/cache 工具）。

总原则：
1) 只要用户在任何时候表达“要生成图片/视频/海报/封面/分镜/可视化效果”，就主动调用 generate。
2) 用户要“基于上一次/某次结果继续改/做同款”，先调用 history 获取序号，再用 generate 的 history_index 继续生成（仅图片可作为参考图）。
3) 调用工具后，必须把工具返回内容（特别是图片/视频链接）原样粘贴到你最终回复正文里，不要只留在工具返回区。
4) prompt 要先把用户意图改写成更适合生成模型的单段落提示词：主体、场景、构图、镜头、光线、风格、细节、（可选）负面约束；信息不足先问 1-3 个澄清问题。
5) 失败处理：若 generate 失败，简要说明原因与下一步，并可建议更换模型/缩短提示词/检查 API_KEY 与配额；注意服务端会自动换模型重试 1 次，你需要在回复里保留该提示信息。

不确定是否该调用时：倾向于先问清楚再调用；但一旦用户确认要生成，就立即调用。
```

## 快速测试
- 文生图：`generate`（模型 `gemini-3.0-pro-image-landscape`）
- 文生视频：`generate`（模型 `veo_3_1_t2v_fast_portrait`）
- 查历史：`history { "scope": "recent", "limit": 5 }`
- 基于历史继续：`generate { "history_index": 1, "history_scope": "recent", ... }`
- 清理缓存：`cache { "action": "prune", "keep": 50 }`

## 工具说明
### generate
- `model`（必填，枚举）
- `prompt`（必填）
- `history_index`（可选，1=最近一条）
- `history_scope`（可选：`recent`/`archive`，默认 `recent`）

限制：
- `history_index` 只复用“图片”结果作为参考图，不支持“视频生视频”
- 本项目 **不支持透传用户上传图片**进行图生图，只能复用历史里的图片结果进行图生图
- 为提高成功率，`generate` 在失败时会自动“换一个模型”重试（次数可通过 `FLOW2API_MCP_GENERATE_MODEL_RETRY_COUNT` 调整），并在结果顶部提示

### history
- `limit`（默认 5）
- `scope`：`recent`（短期）/`archive`（长期，默认 `recent`）

### cache
- `action`：`status`/`clear`/`prune`（默认 `status`）
- `keep`：裁剪保留条数（默认 50）
- `include_history`：是否同时清理/裁剪历史（默认 `false`）

## 历史与缓存
历史文件：
- 短期：`mcp_server/history.json`（默认最多 50 条，可通过 `FLOW2API_MCP_HISTORY_RECENT_SIZE` 调整）
- 长期：`mcp_server/history_archive.json`（默认最多 2000 条，可通过 `FLOW2API_MCP_HISTORY_ARCHIVE_SIZE` 调整）

本机媒体缓存：
- 文件：`mcp_server/url_cache/`
- 索引：`mcp_server/url_cache.json`

相关环境变量：
见上面的“环境变量”表格。

## 常见问题
- `API错误 401`：检查 `FLOW2API_API_KEY`
- `API错误 403`：通常是上游/权限/配额问题
- 链接签名/过期异常：优先检查系统时间是否正确

## License
MIT License
