# 部署与客户端配置

这份文档只解决两件事：

1. 服务怎么跑起来
2. 客户端怎么连

## 先分清 3 个地址

| 用途 | 默认示例 | 说明 |
| --- | --- | --- |
| 上游 API | `http://127.0.0.1:8000` | `FLOW2API_BASE_URL`，给 Flow2API / OpenAI-compatible 上游 |
| MCP HTTP | `http://127.0.0.1:8866/mcp` | 客户端真正连接的 MCP 地址 |
| 缓存图片 | `http://127.0.0.1:8866/mcp-cache/...` | 稳定图片链接 |

## 怎么选

| 场景 | 推荐方式 |
| --- | --- |
| Cherry Studio、本机助手、本机调试 | 本机常驻 HTTP |
| Docker、NAS、云主机、跨设备访问 | Docker / 远程部署 |

## 功能差异

重点只看这 3 条：

- 文生图：所有部署方式都能用
- `history_id` 改图：所有部署方式都能用
- `use_latest_user_image=true`：只有 MCP 进程能直接读到附件目录时可用；远程没挂载共享目录时，要先把图片传到图床或其他可访问 URL，再改用 `image_url`

## 通用前置条件

```bash
python -m pip install -r requirements.txt
```

推荐直接从示例复制一份 `.env`：

```bash
cp .env.example .env
```

PowerShell：

```powershell
Copy-Item .env.example .env
```

然后再按你的实际参数修改：

```dotenv
FLOW2API_BASE_URL=http://127.0.0.1:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
# FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

默认会优先读取当前工作目录下的 `.env`；如果没有，再回退到仓库根目录 `.env`。系统环境变量优先级更高。

说明：

- `FLOW2API_BASE_URL` 填服务根地址，不要自己补 `/v1`
- `FLOW2API_API_KEY` 直接填 token，不要带 `Bearer `
- PowerShell 临时设置环境变量时，用 `$env:NAME="value"`，不要用 `export`

## 方案一：本机常驻 HTTP

这是推荐的本机部署方式。先准备好 `.env`，再启动：

```bash
python -m mcp_server --host 127.0.0.1 --port 8866
```

MCP 地址：

```text
http://127.0.0.1:8866/mcp
```

缓存图地址：

```text
http://127.0.0.1:8866/mcp-cache/<hash>.jpg
```

如果你想直接读取本地附件，再补：

```text
FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

适合这类场景：

- 客户端就在本机
- 想稳定返回缓存链接，不直接吃上游临时 URL
- 需要 `use_latest_user_image=true` 去读本机附件目录

如果需要常驻运行，可以交给 `systemd`、`pm2`、NSSM 或你自己的守护方式。

## 方案二：Docker / 远程部署

仓库里提供的是 [docker-compose.example.yml](../docker-compose.example.yml)。

### 1. 确认关键环境变量

`docker compose` 默认会读取项目根目录的 `.env`。

如果你本机已经能靠 `.env` 跑通，Docker 通常直接复用这几个值：

- `FLOW2API_BASE_URL`
- `FLOW2API_API_KEY`
- `FLOW2API_MCP_URL_CACHE`
- `FLOW2API_MCP_IMAGE_DIR`

复制后本机实际使用的 `docker-compose.yml` 会直接复用本机版本同一份运行时数据：

- `data/url_cache/`
- `data/history.json`
- `data/history_archive.json`

这样做的好处很直接：

- 本机模式生成过的缓存图，Docker 模式下还能继续访问
- 本机与 Docker 的 `history_id`、缓存文件都保持同一份

如果你是从旧版本升级，且旧数据还在 `mcp_server/` 下，请先手动复制到 `data/`：

- `mcp_server/history.json` -> `data/history.json`
- `mcp_server/history_archive.json` -> `data/history_archive.json`
- `mcp_server/url_cache/` -> `data/url_cache/`
- `mcp_server/url_cache.json` -> `data/url_cache.json`

同机测试时，建议再确认这一项：

```dotenv
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://127.0.0.1:8866
```

先复制一份示例文件：

```bash
cp docker-compose.example.yml docker-compose.yml
```

PowerShell：

```powershell
Copy-Item docker-compose.example.yml docker-compose.yml
```

补充说明：

- `host.docker.internal` 适合 Docker Desktop
- Linux 服务器通常要改成宿主机 IP、域名，或容器内可访问的服务名
- `FLOW2API_MCP_URL_CACHE=1` 建议开启，不然很多客户端会拿到会过期的上游临时链接
- `FLOW2API_MCP_EXTERNAL_URL_PREFIX` 要写客户端真正访问容器的地址

### 2. 启动

```bash
docker compose up -d --build
docker compose logs -f
```

默认端口：

- `8866`：MCP HTTP，同时承载 `/mcp-cache/...`

MCP 地址：

```text
http://<server>:8866/mcp
```

### 3. 远程访问缓存图片

如果客户端和容器不在同一台机器，建议设置：

```text
FLOW2API_MCP_EXTERNAL_URL_PREFIX=http://<server>:8866
```

也可以改成你自己的域名：

```text
FLOW2API_MCP_EXTERNAL_URL_PREFIX=https://your-domain.example.com
```

## Docker 下怎么用本地参考图

`use_latest_user_image=true` 读取的是 MCP 进程所在机器能看到的目录。

如果你把服务放进容器里，又想读取宿主机上的本地图片目录，需要额外挂载：

```yaml
environment:
  - FLOW2API_MCP_IMAGE_DIR=/app/user-images
volumes:
  - /path/to/local/images:/app/user-images:ro
```

如果做不到，优先改用：

- `history_id`
- `image_url`

换句话说：

- “继续改上一张” 直接用 `history_id`
- “用刚上传的本地图继续改” 只有本机部署或容器已挂载附件目录时才真正可用
- 服务在远程、图片又传不过去时，先把图片上传到图床、对象存储或其他可访问 URL，再走 `image_url`

## 客户端配置

## `generate` 参数约定

无论本机还是 Docker，`generate` 的外部调用契约都一样，只接受这 5 个扁平字段：

- `model`
- `prompt`
- `history_id`
- `use_latest_user_image`
- `image_url`

规则：

- 必填永远只有 `model` 和 `prompt`
- 三个参考图字段只能有一个有效值
- 纯文本生成时，这三个参考图字段都不要传
- 如果客户端硬塞 `history_id=0`、`image_url=""`、`use_latest_user_image=false` 这类占位值，服务会视为“未传”
- 不要额外再包 `params` / `arguments` / `input`

### Cherry Studio

推荐直接连本地 HTTP MCP：

| 配置项 | 建议值 |
| --- | --- |
| 类型 | `Streamable HTTP` 或等价的 HTTP MCP 模式 |
| URL | `http://127.0.0.1:8866/mcp` |
| 超时 | 建议 `180s` 或更高 |

建议环境变量：

```text
FLOW2API_BASE_URL=http://127.0.0.1:8000
FLOW2API_API_KEY=your-api-key
FLOW2API_MCP_URL_CACHE=1
```

如果要直接读取 Cherry Studio 最近上传的本地图片，再补：

```text
FLOW2API_MCP_IMAGE_DIR=%APPDATA%\CherryStudio\Data\Files
```

### 通用 HTTP MCP 客户端

连接地址通常是：

- 本机常驻 HTTP：`http://127.0.0.1:8866/mcp`
- Docker / 远程部署：`http://<server>:8866/mcp`

如果图片能生成但客户端里打不开，优先检查：

1. 是否开启了 `FLOW2API_MCP_URL_CACHE=1`
2. 当前服务是否真的在跑 `python -m mcp_server --host ... --port ...`
3. 跨机器访问时是否设置了 `FLOW2API_MCP_EXTERNAL_URL_PREFIX`

## 相关文档

- [README](../README.md)
- [参考手册](REFERENCE.md)
