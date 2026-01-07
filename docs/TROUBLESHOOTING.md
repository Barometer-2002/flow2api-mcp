# 常见问题与排查

## 常见错误

- `API错误 401`：检查 `FLOW2API_API_KEY`
- `API错误 403`：通常是上游/权限/配额问题
- `❌ 生成失败：无结果 / empty content extracted`：表示上游 `HTTP 200` 但 MCP 未能从响应中提取到可用内容（文本或图片/视频链接）
- `cherry studio 无法渲染出图片`：未开启 MCP“长时间运行模式”
- `无法cherry studio 上传的图参考`：未设置 `FLOW2API_MCP_CHERRYSTUDIO_FILES_DIR`，或路径错误

## `empty content extracted` 如何排查

1) 看 `generate` 返回的 `<details>` 日志  
如果出现 `debug_dump=...`，可直接打开该文件查看上游原始 SSE 输出（仅用于排查，不会加入 git）。

2) 用脚本直连上游抓原始输出  
见 `scripts/inspect_upstream_chat_completions.py`，支持 `--stream` 输出原始 `data:` 行：

```bash
set FLOW2API_API_KEY=your-key
python scripts/inspect_upstream_chat_completions.py --base-url http://127.0.0.1:8000 --model your-model --stream --prompt "test"
```

