# Flow2API MCP Server

将 [Flow2API](https://github.com/TheSmallHanCat/flow2api) / OpenAI-compatible 上游封装为图片生成 MCP 服务。

这个仓库原生提供 `stdio` MCP 服务；如果你的客户端需要 HTTP 接入，可以再用 [supergateway](https://github.com/supercorp-ai/supergateway) 把它暴露成 Streamable HTTP。

## 这项目适合谁

- 你已经有可用的 Flow2API / OpenAI-compatible 图片上游
- 你想把它接成 MCP，给 Cherry Studio、支持 HTTP MCP 的客户端或自动化流程使用
- 你需要图片历史复用、本地缓存稳定链接、基于本地图片继续改图

## 项目能力

- 启动时自动从上游 `/v1/models` 同步图片模型到 `mcp_server/models.json`
- 提供 `generate`、`history`、`cache` 三个 MCP 工具
- 可把上游临时图片链接缓存到本地并通过内建 HTTP 服务稳定访问
- 支持通过 `history_id` 继续改图，也支持读取本地目录中的最新图片作为参考图

## 功能差异一眼看懂

| 功能 | 本地 `stdio` | 本地 Streamable HTTP | Docker / 远程部署 |
| --- | --- | --- | --- |
| 文生图 | 可用 | 可用 | 可用 |
| 基于历史改图 `history_id` | 可用 | 可用 | 可用 |
| 基于用户上传图改图 `use_latest_user_image=true` | 可用 | 可用，但 MCP 和附件目录必须在同一台机器 | 只有容器已挂载附件目录时可用，否则不可用 |
| 基于远程图片 URL 改图 `image_url` | 可用 | 可用 | 可用 |

可以直接记成这 3 句话：

- 文生图最简单，所有部署方式都能用
- 基于历史图继续改图最稳，所有部署方式都能用
- 基于用户上传图改图只在 MCP 进程能直接读到附件目录时可用；远程场景如果没挂载共享目录，就需要先把图片传到图床或其他可访问 URL，再走 `image_url`

## 先选部署方式

| 场景 | 推荐方式 | 适合什么情况 |
| --- | --- | --- |
| 只在本机用 Cherry Studio 之类的 `stdio` 客户端 | 本地 `stdio` | 最简单，不需要 supergateway |
| 客户端需要 HTTP MCP，但服务和客户端在同一台机器 | 本地 Streamable HTTP | 本机起 `supergateway` 暴露 `/mcp` |
| 要放到 Docker 或远程主机上 | Docker / 远程部署 | 方便长期运行、多客户端接入 |

详细步骤见：

- [部署与客户端配置](docs/DEPLOY.md)
- [参考手册](docs/REFERENCE.md)

## 快速开始

### 1. 克隆并安装依赖

```bash
git clone https://github.com/Barometer-2002/flow2api-mcp.git
cd flow2api-mcp
python -m pip install -r requirements.txt
```

### 2. 配置核心环境变量

下面这些已经覆盖大多数实际使用场景：

| 变量 | 什么时候需要 | 说明 |
| --- | --- | --- |
| `FLOW2API_BASE_URL` | 总是需要 | 上游服务根地址，不要手动带 `/v1` |
| `FLOW2API_API_KEY` | 大多数上游都需要 | 直接填 token，不带 `Bearer ` 前缀 |
| `FLOW2API_MCP_URL_CACHE=1` | 推荐开启 | 让图片链接落地到本地缓存，尤其适合远程部署或客户端容易吃临时链接失败的场景 |
| `FLOW2API_MCP_IMAGE_DIR` | 需要“用本地最新图片做参考图”时 | 例如 Cherry Studio 的附件目录；只有 MCP 进程能直接读到这个目录时才有效 |
| `FLOW2API_MCP_EXTERNAL_URL_PREFIX` | 远程 / Docker 部署时常用 | 把缓存图片地址改写成客户端可访问的外部地址 |

### 3. 选择一种启动方式

#### 方式 A：本地 `stdio`

最适合 Cherry Studio 或其他原生支持 `stdio` MCP 的客户端。

```bash
export FLOW2API_BASE_URL=http://127.0.0.1:8000
export FLOW2API_API_KEY=your-api-key
python -m mcp_server
```

#### 方式 B：本地 Streamable HTTP

当客户端需要 HTTP MCP 接口时，在本机用 `supergateway` 包一层即可：

```bash
export FLOW2API_BASE_URL=http://127.0.0.1:8000
export FLOW2API_API_KEY=your-api-key
npm install -g supergateway
supergateway --stdio "python -m mcp_server" --outputTransport streamableHttp --port 8000
```

MCP 入口地址：

```text
http://127.0.0.1:8000/mcp
```

#### 方式 C：Docker / 远程部署

先编辑仓库内的 [docker-compose.yml](docker-compose.yml)，至少填好：

```yaml
FLOW2API_BASE_URL=http://host.docker.internal:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_HOST=0.0.0.0
```

然后启动：

```bash
docker compose up -d --build
```

默认 MCP 入口地址：

```text
http://<server>:8866/mcp
```

如果客户端不和容器在同一台机器上，通常还要设置：

```text
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://<server>:46262
```

否则客户端可能拿到一个自己无法访问的缓存图片地址。

## 客户端快速配置

### Cherry Studio

推荐直接走 `stdio`：

| 配置项 | 建议值 |
| --- | --- |
| 类型 | `STDIO` |
| 命令 | 你的 Python 解释器，例如 `python` 或虚拟环境里的 Python |
| 参数 | `-m mcp_server` |
| 工作目录 | 仓库根目录（如果客户端支持设置） |
| 超时 | 建议 `180s` 或更高 |

如果客户端不能设置工作目录，给它补一个环境变量：

```text
PYTHONPATH=/path/to/flow2api-mcp
```

如果你想让 `use_latest_user_image=true` 直接读取 Cherry Studio 的本地附件，再加上：

```text
FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

这条只适用于 MCP 跟这个目录在同一台机器，或容器已经挂载了这个目录的情况。

### 支持 HTTP MCP 的客户端

如果你的客户端支持 Streamable HTTP，直接填 MCP URL：

- 本地 supergateway：`http://127.0.0.1:8000/mcp`
- Docker / 远程部署：`http://<server>:8866/mcp`

如果图片能生成但客户端里显示裂开，优先检查缓存服务是否对客户端可达，通常要回看 `FLOW2API_MCP_URL_CACHE`、`FLOW2API_MCP_HOST` 和 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`。

更完整的部署和客户端说明见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 工具速览

- `generate`：文生图 / 图生图，支持 `history_id`、`use_latest_user_image`、`image_url`
- `history`：查看最近历史或归档历史，找到可复用的 `history_id`
- `cache`：查看、裁剪或清理本地图片缓存与历史记录

其中最重要的部署差异是：

- 文生图：所有部署方式都可用
- `history_id` 改图：所有部署方式都可用
- `use_latest_user_image`：只有本机目录可见或已挂载共享目录时可用
- 远程没法直接传本地文件时：先上传到图床或其他可访问地址，再改用 `image_url`

完整参数、配置和排障见 [docs/REFERENCE.md](docs/REFERENCE.md)。

## 下一步去哪里看

- [部署与客户端配置](docs/DEPLOY.md)：本地、HTTP、Docker、远程部署，以及 Cherry Studio / HTTP 客户端接法
- [参考手册](docs/REFERENCE.md)：高级配置、工具参数、内建 prompts 和故障排查
- [更新日志](CHANGELOG.md)
