# 工具与用法

本 MCP 包含 3 个工具：`generate` / `history` / `cache`。

## 逻辑流程图（Mermaid）

> 说明：需要你的 Markdown 渲染器支持 Mermaid 才会显示为流程图；不支持时会显示为代码块。

```mermaid
flowchart TD
  U[用户需求] -->|生成图片/视频| G[generate]
  U -->|查看历史| H[history]
  U -->|缓存/清理| C[cache]

  subgraph Gen[generate（严格参考图选择）]
    G --> NeedRef{是否需要参考图?}
    NeedRef -->|否| T2[纯文本生成]
    NeedRef -->|是| RefParam{是否提供参考参数?}
    RefParam -->|history_id| FromHist[从历史取图→转 data_uri→发给上游]
    RefParam -->|use_latest_user_image=true| FromUpload[需启用“用户最新上传图导入”→取最新上传→转 data_uri→发给上游]
    RefParam -->|都没有| Ask[先 history(recent) 让用户确认→再用 history_id 调 generate]
  end

  subgraph Hist[history（输出按需）]
    H --> WantList{用户是否明确要“查看历史”?}
    WantList -->|是| FullList[贴完整列表]
    WantList -->|否（仅定位参考图）| OnlyPick[只贴选中项；不唯一/找不到才贴候选]
  end

  subgraph Cache[cache（防误删）]
    C --> Danger{include_history=true 且 action=clear/prune?}
    Danger -->|否| Ok[正常执行/展示结果]
    Danger -->|是| Confirm{confirm=true?}
    Confirm -->|否| Warn[提示风险并要求 confirm=true]
    Confirm -->|是| Do[执行删除/裁剪历史]
  end
```

## 1) `generate`（生成）

必填参数：
- `model`：模型名称（从 `mcp_server/models.json` 的 `models` 中选）
- `prompt`：生成提示词

可选参数（用于“带图”继续生成）：
- `history_id`：稳定历史序号（来自 `history` 返回列表中的标题序号；**不会**随列表变化）
- `use_latest_user_image`：从“用户上传目录”提取“最新文件”作为参考图（需要设置 `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR`）

常见用法示例：
- 文生图：`generate { "model": "gemini-3.0-pro-image-landscape", "prompt": "..." }`
- 文生视频：`generate { "model": "veo_3_1_t2v_fast_landscape", "prompt": "..." }`
- 用历史图片继续生图：`generate { "history_id": 123, "model": "gemini-3.0-pro-image-landscape", "prompt": "..." }`
- 取最新上传图继续生图：`generate { "use_latest_user_image": true, "model": "gemini-3.0-pro-image-landscape", "prompt": "..." }`

注意：
- `history_id` 仅用于“复用图片作为参考图”，不支持把视频当作参考图。
- 视频模型是否可用/返回格式取决于上游：本项目期望上游最终给出可访问的 `.mp4/.webm` 链接，并会统一包装为 `[video](url)`。
- 视频生成通常耗时更长、失败重试成本更高，且不同上游的任务轮询/返回形态差异较大：如你对稳定性要求更高，建议优先使用上游原生调用方式（例如直接调用 Flow2API/OpenAI-compatible 接口）。

## 2) `history`（历史）

参数：
- `history_id`：可选；指定则只返回该条记录（用于“查询某一条历史信息”，避免输出全列表）
- `query`：可选；关键词搜索（匹配不唯一则返回候选摘要；唯一则直接返回单条）
- `keyword`：可选；同 `query`（兼容别名）
- `limit`：返回条数（默认 5）
- `scope`：`recent` / `archive`（默认 `recent`；跨会话更推荐用 `archive`）

示例：
- `history { "history_id": 123 }`
- `history { "query": "水墨" }`
- `history { "scope": "recent", "limit": 5 }`
- `history { "scope": "archive", "limit": 20 }`

返回内容说明：
- 标题行前的数字是稳定的 `history_id`（用于 `generate.history_id`）
- `📦` 表示已命中本机缓存（会显示为 `http://127.0.0.1:<port>/mcp-cache/...`）
- `🌐` 表示仍是上游返回的源链接（未缓存或未命中缓存）
- 图片会用 Markdown 的 `![...](url)` 直接渲染；视频统一用 `[video](url)` 形式

## 3) `cache`（缓存/历史清理）

参数：
- `action`：`status` / `clear` / `prune`（默认 `status`）
- `keep`：`prune` 时保留条数（默认 50）
- `include_history`：是否同时清理/裁剪历史（默认 `false`）
- `confirm`：删除历史记录确认开关（默认 `false`；当 `include_history=true` 且 `action=clear/prune` 时必须为 `true`）

示例：
- `cache { "action": "status" }`
- `cache { "action": "prune", "keep": 50 }`
- `cache { "action": "clear", "include_history": false }`
- `cache { "action": "clear", "include_history": true, "confirm": true }`
- `cache { "action": "prune", "keep": 50, "include_history": true, "confirm": true }`

注意：
- `clear/prune` 会删除本地缓存文件（`mcp_server/url_cache/` 等）。