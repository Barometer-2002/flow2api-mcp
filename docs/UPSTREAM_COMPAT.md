# 上游兼容范围

本项目只兼容 OpenAI Chat Completions（`/v1/chat/completions`）的 SSE/非 SSE 返回。

## 图片结果（兼容两种写法）

### 1) 标准 `content` 多模态 parts（推荐）

- `choices[0].delta.content` / `choices[0].message.content` 为数组
- 图片以 `{"type":"image_url","image_url":{"url":"..."}}` 的 part 出现

### 2) 代理扩展 `images` 字段（你这类上游常见）

- 流式：`choices[0].delta.images[*].image_url.url`（常见为 `data:image/...;base64,...`）
- 非流式：`choices[0].message.images[*].image_url.url`

当上游返回 `data:image/...;base64,...` 时，MCP 会将图片落盘到本机缓存目录，并返回 `http://127.0.0.1:<port>/mcp-cache/...`，避免把超长 base64 直接输出到对话里。

