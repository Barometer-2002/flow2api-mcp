# 部署与客户端配置

这份文档专门回答两个问题：

1. 这个仓库应该怎么跑起来？
2. 应该选 `stdio`、本地 HTTP，还是 Docker / 远程部署？

## 先理解传输方式

这个仓库里的 Python 服务本身跑的是 `stdio` MCP：

```bash
python -m mcp_server
```

如果客户端要求通过 HTTP 连接 MCP，就再用 `supergateway` 把 `stdio` 包装成 Streamable HTTP。

## 选型建议

| 场景 | 建议 | 为什么 |
| --- | --- | --- |
| Cherry Studio、本机助手、本机调试 | 本地 `stdio` | 配置最少，问题最少 |
| 客户端支持 HTTP MCP，但和服务在同一台机器 | 本地 Streamable HTTP | 方便 HTTP 客户端直连 |
| 云主机、NAS、Docker、多人共用 | Docker / 远程部署 | 更适合常驻运行和跨设备访问 |

## 功能可用性矩阵

这是最容易搞混的一块，先看结论：

| 功能 | 本地 `stdio` | 本地 Streamable HTTP | Docker / 远程部署 |
| --- | --- | --- | --- |
| 文生图 | 可用 | 可用 | 可用 |
| 基于历史改图 `history_id` | 可用 | 可用 | 可用 |
| 基于用户上传图改图 `use_latest_user_image=true` | 可用 | 可用，但附件目录必须和 MCP 同机 | 只有挂载了附件目录时可用 |
| 基于远程图片 URL 改图 `image_url` | 可用 | 可用 | 可用 |

直接记忆：

- 文生图最简单，所有部署方式都能用
- 基于历史的改图最稳，所有部署方式都能用
- 基于用户上传图的改图，只在 MCP 进程能直接读取附件目录时可用
- 如果是远程部署且没有共享 / 挂载附件目录，就要先解决图片上传传递问题，例如传到图床，再把 URL 交给 `image_url`

## 通用前置条件

- Python 3.10+（建议）
- 可访问的 Flow2API / OpenAI-compatible 图片上游
- 上游 API Key（如果你的上游开启了认证）

安装 Python 依赖：

```bash
python -m pip install -r requirements.txt
```

最基本的环境变量：

```bash
export FLOW2API_BASE_URL=http://127.0.0.1:8000
export FLOW2API_API_KEY=your-api-key
```

说明：

- `FLOW2API_BASE_URL` 填服务根地址，不要自己补 `/v1`
- `FLOW2API_API_KEY` 直接填 token，不要带 `Bearer `

## 方案一：本地 `stdio`

最适合直接接 Cherry Studio 这类原生支持 `stdio` 的客户端。

启动命令：

```bash
python -m mcp_server
```

你会看到模型同步日志，然后服务进入 MCP `stdio` 运行状态。

适合这个方案的情况：

- 客户端和 MCP 在同一台机器
- 不需要对外暴露 HTTP MCP 入口
- 想最小化中间层

## 方案二：本地 Streamable HTTP

适合支持 HTTP MCP 的客户端，但服务仍然跑在本机。

先安装 `supergateway`：

```bash
npm install -g supergateway
```

然后启动：

```bash
supergateway --stdio "python -m mcp_server" --outputTransport streamableHttp --port 8000
```

默认 MCP 入口地址：

```text
http://127.0.0.1:8000/mcp
```

这套方式的好处：

- Python 侧保持项目原生入口，不改代码
- 需要 HTTP 的客户端可以直接连 `/mcp`
- 适合本地调试和轻量使用

## 方案三：Docker / 远程部署

仓库已经提供了 [docker-compose.yml](../docker-compose.yml)。

### 第一步：准备持久化目录

为了保存历史记录和本地缓存，建议先准备宿主机目录：

```bash
mkdir -p data/url_cache
touch data/history.json data/history_archive.json
```

如果你在 Windows 上，也请手动创建同名空文件和目录，避免 bind mount 把“文件路径”误建成目录。

### 第二步：修改 `docker-compose.yml`

至少确认这些变量：

```yaml
FLOW2API_BASE_URL=http://host.docker.internal:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
FLOW2API_MCP_HOST=0.0.0.0
```

说明：

- `host.docker.internal` 适合 Docker Desktop
- 如果你在 Linux 服务器上跑容器，通常要改成宿主机 IP、域名，或者一个容器内可访问的服务名
- `FLOW2API_MCP_URL_CACHE=1` 强烈建议开启，不然很多客户端会拿到容易过期的上游临时图片链接
- `FLOW2API_MCP_HOST=0.0.0.0` 让缓存 HTTP 服务能被容器外访问

### 第三步：启动

```bash
docker compose up -d --build
docker compose logs -f
```

默认端口：

- `8866` -> MCP Streamable HTTP 入口
- `46262` -> 图片缓存 HTTP 服务

默认 MCP 入口地址：

```text
http://<server>:8866/mcp
```

### 第四步：远程访问缓存图片

如果客户端不和容器在同一台机器，建议设置：

```text
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://<server>:46262
```

或：

```text
FLOW2API_MCP_EXTERNAL_URL_PREFIX=https://your-domain.example.com
```

这样返回给客户端的缓存图片地址会改写成外部可访问的地址，而不是容器内的回环地址。

## Docker 场景下使用本地参考图

`use_latest_user_image=true` 读取的是 **MCP 进程所在机器能看到的目录**。

如果你把服务放进容器里，又想让它读取宿主机上的本地图片目录，需要额外挂载：

```yaml
environment:
  - FLOW2API_MCP_IMAGE_DIR=/app/user-images
volumes:
  - /path/to/local/images:/app/user-images:ro
```

如果做不到这一点，优先改用：

- `history_id`：基于历史结果继续改图
- `image_url`：直接给可访问的图片 URL

换句话说：

- “继续改上一张” 这类需求，不受部署方式影响，直接用 `history_id`
- “用我刚上传的本地图片继续改” 这类需求，只有本机部署或容器已挂载附件目录时才真正可用
- 如果服务在远程，客户端图片又没法直接传到服务所在机器，就需要先把图片上传到图床、对象存储或任意可访问 URL，再走 `image_url`

## 关于图片缓存

开启 `FLOW2API_MCP_URL_CACHE=1` 后，服务会把图片缓存到：

- `mcp_server/url_cache/`
- `mcp_server/url_cache.json`

并通过内建 HTTP 服务暴露：

```text
http://127.0.0.1:46262/mcp-cache/<hash>.<ext>
```

远程部署时，如果你不设置 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`，客户端很可能拿到一个自己访问不到的地址。

## 部署前检查清单

- 你填的是 `FLOW2API_BASE_URL` 根地址，而不是 `.../v1`
- `FLOW2API_API_KEY` 对目标模型有权限
- 远程 / Docker 场景已开启 `FLOW2API_MCP_URL_CACHE=1`
- Docker 场景已把 `FLOW2API_MCP_HOST` 设为 `0.0.0.0`
- 需要本地图片参考图时，`FLOW2API_MCP_IMAGE_DIR` 对 MCP 进程可见

## 客户端配置

这部分保留部署完成后最常见的客户端接法，避免你来回跳文档。

### Cherry Studio

推荐直接连本地 `stdio`：

| 配置项 | 建议值 |
| --- | --- |
| 类型 | `STDIO` |
| 命令 | `python` 或你的虚拟环境 Python |
| 参数 | `-m mcp_server` |
| 工作目录 | 仓库根目录 |
| 超时 | 建议 `180s` 或更高 |

建议环境变量：

```text
FLOW2API_BASE_URL=http://127.0.0.1:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
```

如果你希望 `use_latest_user_image=true` 直接读取 Cherry Studio 最近上传的本地图片，再补：

```text
FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

如果客户端不能设置工作目录，补一个：

```text
PYTHONPATH=/path/to/flow2api-mcp
```

### 通用 HTTP MCP 客户端

如果客户端支持 Streamable HTTP，连接地址通常是：

- 本地 supergateway：`http://127.0.0.1:8000/mcp`
- Docker / 远程部署：`http://<server>:8866/mcp`

如果图片能生成但客户端里打不开，优先检查：

1. 是否开启了 `FLOW2API_MCP_URL_CACHE=1`
2. Docker / 远程部署是否把 `FLOW2API_MCP_HOST` 设为 `0.0.0.0`
3. 跨机器访问时是否设置了 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

### 参考图在不同部署方式下怎么选

`generate` 支持三种参考图来源：

- `history_id`
- `use_latest_user_image=true`
- `image_url`

建议这样选：

- 继续改上一张图：优先用 `history_id`
- 本机客户端刚上传了新图，且 MCP 真能访问附件目录：用 `use_latest_user_image=true`
- 远程部署或自动化流程：优先用 `image_url`

如果 MCP 进程根本访问不到本地附件目录，就不要依赖 `use_latest_user_image=true`，而是先解决图片上传传递问题。

## 相关文档

- [README](../README.md)
- [参考手册](REFERENCE.md)
