# 🩺 常见问题与排查 (V2)

## 常见系统错误代码

- `❌ HTTP 401 Unauthorized`：未授权。请检查你的环境变量 `FLOW2API_API_KEY` 是否填写正确。
- `❌ HTTP 403 Forbidden`：权限不足。通常是上游模型接口（Flow2API/OpenAI-compatible）判断你所在的网络 IP 存在异常或账号被封禁。
- `❌ HTTP 404 Not Found`：一般发生在未填写 `FLOW2API_BASE_URL` 或没有正确重定向到 `/v1/chat/completions` 时。如果你的代理不支持自动补齐，请确保 URL 不带尾部后缀路径。

---

## 具体场景排查

### 1) "图片生成成功了，但在对话框里显示裂开/加载不出"
这由于临时图从上游生成后，MCP 在将 URL 呈递给大语言模型时失效导致的。
**解决办法：**
1. 请进入 `docker-compose.yml` 或是系统环境变量，强制开启设置 `FLOW2API_MCP_URL_CACHE=1`。（V2 中此项默认在 Docker 中推荐开启）
2. 如果你的客户端（如 Cherry Studio）和 MCP 不在同一个物理主机（比如跑在云端 Docker 里），你必须设置 `FLOW2API_MCP_EXTERNAL_URL_PREFIX` 把缓存前缀代理为你自己的公网 IP 或域名。

### 2) "从提示词里提取不到生成内容 (empty content)" 
大模型返回了 `HTTP 200`，但它可能返回的是一通系统报错信息（比如“您的账户被限流了”），所以 MCP 找不到 `![img](url)` 的 markdown 图片链接。
**解决办法：**
- 修改环境配置，临时启用 `FLOW2API_MCP_DEBUG=1`，重启服务，通过服务输出的 stderr 可以精准捕获它究竟返回了那一句拦截日志。随后可以去对应的分销商/源站处理上游拦截问题。

### 3) "无法使用本地的图片（找不到文件）"
**解决办法：**
1. 检查环境变量设置。V2 统一为 `FLOW2API_MCP_IMAGE_DIR`。
2. 确保配置的值是一个【绝对路径的真实文件夹】，如果是 Windows，请确保反斜杠被转义（例：`C:\\Users\\xxx\\Pictures`）。
3. 如果是在 Docker 容器内运行，你的宿主机路径需要被通过 `volumes:` 挂载进容器能读到的一个 `/app/images/` 位置，并将环境变量指向挂载点，否则容器是抓不到物理机外面的文件的。
