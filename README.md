# Flow2API MCP Server

一个基于 stdio 的 MCP 服务：将 [Flow2API](https://github.com/TheSmallHanCat/flow2api) / OpenAI-compatible 上游封装为 MCP 工具（`generate` / `history` / `cache`）。

> 说明：这是个人项目，**不保证兼容性与长期维护**。若你对稳定性要求更高，建议优先使用上游原生调用方式。目前只在**windows**搭配 **Cherry Studio** 客户端使用。

工具：
- `generate`：文生图 / 文生视频；也支持用历史图片继续生成
- `history`：查看跨会话混合的生成历史（用稳定 `history_id` 复用）
- `cache`：查看/清理/裁剪本机媒体缓存


## 安装

```bash
pip install -r requirements.txt
```

## 最小配置（快速开始）

仅需 2 个环境变量：
- `FLOW2API_BASE_URL`：上游服务地址（默认 `http://localhost:8000`）
- `FLOW2API_API_KEY`：API Key（不要带 `Bearer ` 前缀）

## 设计速览（缓存 / 本地上传）

- 本机媒体缓存（推荐）：开启 `FLOW2API_MCP_URL_CACHE=1` 后，MCP 会把上游返回的图片/视频链接下载到本地 `mcp_server/url_cache/`，并通过内置 HTTP（默认 `http://127.0.0.1:46262/mcp-cache/...`）提供稳定访问，避免上游临时链接失效。
- 
- Cherry Studio 本地附件上传参考图（推荐）：由于 MCP 无法直接读取对话附件，本项目通过读取 Cherry Studio 本地附件目录（`FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR`）来“导入用户最新上传图”，用于图生图参考，未配置则只能通过历史生图指定参考图。
- 全部环境变量与配置选项见 `docs/CONFIG.md`。

## Cherry Studio MCP配置

- 类型：`标准输入/输出 (stdio)`
- 命令：你的 Python 解释器路径
- 参数：使用脚本路径：`D:\\github\\flow2api-mcp\\mcp_server\\server.py`
- 环境变量：至少填 `FLOW2API_BASE_URL`、`FLOW2API_API_KEY`
- 推荐补充以下环境变量：
  - 本机缓存：`FLOW2API_MCP_URL_CACHE=1`
  - Cherry Studio 上传图目录：`FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR=C://Users//<YOUR_USERNAME>//AppData//Roaming//CherryStudio//Data//Files`
- 长时间运行模式： `开启`
- 超时：生成耗时，建议设置为 `180` 秒或更高

> 说明：由于MCP服务是临时进程，为了本地缓存链接的正常显示，需要`开启`“长时间运行模式”。
> 若你使用其他支持 MCP 的客户端，请自行解决“本机缓存链接访问”问题。

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

参考图（避免丢失历史上下文）：
1) 先区分“底图（Base）”与“素材（Element）”：工具只接收 1 张参考图（Base），Element 需要你转译成文字写进 prompt。
2) 新建/重绘：用户说“参考这张图生成/把这图变成…” → generate(use_latest_user_image=true)。
3) 迭代修改：用户说“继续/再改改/加上/变成视频…” → 必须使用历史底图：generate(history_id=...)；不知道 history_id 先 history(recent) 查。
4) 冲突场景：用户新上传图 + “把它加到上一张/历史图里” → Base=history_id；把新图里关键元素用文字写入 prompt。
5) 文本里出现的图片链接/文件名/哈希：只当作 history(query=...) 的检索线索，不要当参考图直接传。

输出要求：
- 调用 generate 后，把图片/视频链接使用 MD 形式粘贴到最终正文（不要只留在工具返回区）。
- cache 清理历史需要 confirm=true（include_history=true 且 clear/prune）。
```

## 自定义模型配置（`mcp_server/models.json`）

如果你想使用其他openai格式的模型，或调整默认模型与选型指南，可编辑 `mcp_server/models.json` 文件尝试，不保证兼容性。

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
