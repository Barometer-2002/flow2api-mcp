# Flow2API MCP Server

一个基于 stdio 的 MCP 服务：将 Flow2API / OpenAI-compatible 上游封装为 MCP 工具（`generate` / `history` / `cache`）。

> 说明：这是个人项目，**不保证兼容性与长期维护**。若你对稳定性要求更高，建议优先使用上游原生调用方式。

工具：
- `generate`：文生图 / 文生视频；也支持用历史图片继续生成
- `history`：查看跨会话混合的生成历史（用稳定 `history_id` 复用）
- `cache`：查看/清理/裁剪本机媒体缓存（可选）


## 安装

```bash
pip install -r requirements.txt
```

## 最小配置（快速开始）

仅需 2 个环境变量：
- `FLOW2API_BASE_URL`：上游服务地址（默认 `http://localhost:8000`）
- `FLOW2API_API_KEY`：API Key（不要带 `Bearer ` 前缀）

## 设计速览（缓存 / 本地上传）

- 本机媒体缓存（可选）：开启 `FLOW2API_MCP_URL_CACHE=1` 后，MCP 会把上游返回的图片/视频链接下载到本地 `mcp_server/url_cache/`，并通过内置 HTTP（默认 `http://127.0.0.1:46262/mcp-cache/...`）提供稳定访问，避免上游临时链接失效。
- Cherry Studio 本地上传图（可选）：由于 MCP 无法直接读取对话附件，本项目通过读取 Cherry Studio 上传目录（`FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR`）来“导入用户最新上传图”，用于图生图参考（`use_latest_user_image=true` 或 `local_file=file:///...`）。

## MCP 客户端配置（通用 JSON）

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

说明：
- `cwd` 必须指向本项目根目录（例如 `D:\\github\\flow2api-mcp`）
- Windows 路径在 JSON 里用 `\\`
- 配置必须是纯 JSON（不能写 `//` 注释、不能有多余逗号）

## Cherry Studio 配置（表单）

- 类型：`标准输入/输出 (stdio)`
- 命令：你的 Python 解释器路径
- 参数（推荐）：`-m mcp_server`
  - 如果客户端不支持多参数输入，也可使用脚本路径：`D:\\github\\flow2api-mcp\\mcp_server\\server.py`
- 环境变量：至少填 `FLOW2API_BASE_URL`、`FLOW2API_API_KEY`
- 超时：建议设置为 `120` 秒或更高

## 工具速览

本 MCP 提供 3 个工具：`generate` / `history` / `cache`（详细参数与流程图见 `docs/TOOLS.md`）。

常见用法示例：
- 文生图：`generate { "model": "gemini-3.0-pro-image-landscape", "prompt": "..." }`
- 用历史图片继续生图：`generate { "history_id": 123, "model": "gemini-3.0-pro-image-landscape", "prompt": "..." }`
- 查最近历史：`history { "scope": "recent", "limit": 5 }`
- 清理本机缓存：`cache { "action": "clear", "include_history": false }`

## 系统提示词（可选）

通常不需要额外系统提示词；如你希望模型更稳定地调用 MCP，可使用以下简版补强：

```
你已接入 MCP：flow2api（generate/history/cache）。

补强重点（易错点）：
1) 图生图必须显式给参考图来源：history_id / use_latest_user_image / local_file（local_file 禁止 http(s)）。
2) 不要死查 history：只有需要用户确认 history_id 时才调用 history。
3) generate 返回后必须把图片/视频链接粘贴到最终正文（不要只留在工具返回区）。
4) cache 删除历史必须 confirm=true（include_history=true 且 clear/prune）。
```

## 自定义模型配置（`mcp_server/models.json`）

模型列表与选型说明由 `mcp_server/models.json` 管理：
- `models`：允许使用的模型名称列表（也用于 `generate.model` 的校验）
- `default_model`：默认模型
- `selection_guide_lines`：给模型/用户看的选型指南（按行写）

修改后需重启 MCP 生效；可先备份原文件再调整（例如 `mcp_server/models.json.bak`）。

## 文档

- 配置与环境变量：`docs/CONFIG.md`
- 工具与用法（含流程图）：`docs/TOOLS.md`
- 常见问题与排查：`docs/TROUBLESHOOTING.md`
- 上游兼容范围：`docs/UPSTREAM_COMPAT.md`

## License

MIT License
