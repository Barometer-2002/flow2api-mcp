# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-03-16

### Added
- `.env.example`，方便本机与 Docker 部署直接复制后修改
- `docker-compose.example.yml`，作为远端保留的 Docker 示例文件
- 运行时路径、模型配置、工具提示相关测试，保证当前版本行为固定

### Changed
- MCP 服务统一为原生 Streamable HTTP 启动，不再依赖 `supergateway`
- 模型列表、默认模型、模型选型提示改为完全由 `mcp_server/models.json` 手动控制
- 运行时缓存与历史记录统一使用 `data/` 目录
- Docker 使用方式简化为“复制 `docker-compose.example.yml` 为本地 `docker-compose.yml` 后再启动”
- `generate` / `history` / `cache` 的工具说明与参数约束重新收口，减少客户端误调用

### Fixed
- 修复缓存图片链接在本机与 Docker 场景下的持久化访问问题
- 修复 `history_id=0`、`image_url=\"\"`、`use_latest_user_image=false` 这类占位参数导致的误判
- 修复历史文件父目录不存在时无法保存的问题
