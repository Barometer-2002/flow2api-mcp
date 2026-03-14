# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-03-15

### 🎉 Initial Release (from flow2api-mcp rewrite)

#### Added
- **HTTP 传输支持** — 通过 supergateway 将 stdio MCP 桥接为 HTTP SSE，支持 Cursor、Claude Desktop 等更多客户端
- **Docker 部署** — 一键 Docker/Docker Compose 部署
- **模型自动同步** — 启动时从上游 `/v1/models` 自动拉取图片模型列表
- **Gemini 3.1 Flash 系列** — 支持最新 `gemini-3.1-flash-image-*` 全系列（标准/2K/4K + 多画幅）
- **外部 URL 前缀** — `FLOW2API_MCP_EXTERNAL_URL_PREFIX` 支持 Docker/远程部署时媒体缓存链接正确暴露

#### Changed
- 更新 `models.json` 默认模型为 `gemini-3.1-flash-image-landscape`
- 精简项目结构，聚焦核心运行文件

#### Based on
- [flow2api-mcp](https://github.com/Barometer-2002/flow2api-mcp) — 原始 stdio 版本
- [flow2api](https://github.com/TheSmallHanCat/flow2api) — 上游 API 服务
