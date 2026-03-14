# 🛠 工具与用法 (V2)

本 MCP 专注于图片生成与修改场景，共包含 3 个原生工具：`generate` / `history` / `cache`。

---

## 1) `generate`（生成与编辑图片）

这是与上游模型交互最核心的工具。

### 参数定义：
* **`model`** (必填)：模型名称（会自动从上游同步，或从 `mcp_server/models.json` 读取枚举）
* **`prompt`** (必填)：图片生成的提示词。

### 参考图参数（如果需要图生图，三选一）：
* **`history_id`**：传入通过 `history` 查询到的稳定历史序号。它允许基于上一张你生成的图片进行连续重绘、修改构图或添加元素。
* **`use_latest_user_image`**：填入 `true`，MCP 会扫描你配置在 `FLOW2API_MCP_IMAGE_DIR` 目录中的最新的一张图片作为参考。适合直接拖入一张图片要求 AI 帮你修改画风。
* **`image_url`**：填入一个外部带有 http/https 的公网图片链接。MCP 会自动下载它并作为参考图传给上游。适合运行在云端的 Agent 或自动流使用。

### 用法示例：
```jsonc
// 纯文生图
{ "model": "gemini-3.1-flash-image-landscape", "prompt": "一只可爱的猫咪在赛博太空站" }

// 用历史图片继续生图
{ "history_id": 12, "model": "gemini-3.0-pro-image-landscape", "prompt": "把背景改成水墨画风格" }

// 指定公网 URL 作为生图源点
{ "image_url": "https://example.com/tree.jpg", "model": "imagen-4.0-generate-preview-landscape", "prompt": "让这棵树燃烧起来" }
```

> **注意：** V2 已彻底移除了对视频模型的支持（如 `veo_3_1_t2v`），只专注服务好所有的图片模型调用与缓存。

---

## 2) `history`（历史与复用查询）

当你需要查看上一次生成的原图，或者查找某个图片的 `history_id` 以便修改它的时候使用。

### 参数定义：
* **`history_id`**：可选；如果提供，则只返回该条具体记录，用于获取某一条历史图的精确上下文。
* **`limit`**：返回的最近历史记录条数（默认 5）
* **`scope`**：`recent`（最近） / `archive`（长期归档文件）

### 呈现形态：
* 标题行中带有的数字即为稳定的 `history_id`（用于 `generate.history_id` 传参）。
* 若启用了本地缓存 HTTP 服务，图片会被本地替换并稳定呈现为 `http://127.0.0.1:<port>/mcp-cache/...`。
* `📦` 表示已经成功被存入你的本地磁盘。

---

## 3) `cache`（本地媒体缓存管理）

控制由 `FLOW2API_MCP_URL_CACHE=1` 带来的本地缓存存储，以免磁盘被旧图片塞满。

### 参数定义：
* **`action`**：执行动作。包括 `status` (查看容量进度) / `clear` (一键清空全部图片) / `prune` (裁剪旧图留新图)。
* **`keep`**：当使用 `prune` 时，保留最新缓存的条数（默认 50）。
* **`include_history`**：是否在删除图片缓存的同时，把 json 数据库中的历史生成指令条目也干掉（默认 `false`）。
* **`confirm`**：双重确认安全锁。凡是涉及到删除数据的动作，都必须传递 `confirm=true`，否则 MCP 会予以拒绝拦截。

### 示例用法：
```jsonc
// 查看当前占据了磁盘多大，还有多少张图片
{ "action": "status" }

// 删掉全盘图片，同时也删掉历史生成的 JSON 记忆：
{ "action": "clear", "include_history": true, "confirm": true }
```
