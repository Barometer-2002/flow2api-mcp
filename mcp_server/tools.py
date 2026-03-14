"""MCP tool definitions, handlers, and prompt templates."""

from __future__ import annotations

import asyncio
import difflib
from typing import Any

from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
)

from .cache import (
    URL_CACHE_DIR,
    cache_urls,
    download_url_as_base64,
    ensure_cache_http_server,
    get_cached_local_url,
    import_local_file,
    is_local_cache_url,
    pick_user_image_paths,
    replace_urls_with_cached,
    store_local_media,
    url_cache,
)
from .client import http_client, stream_chat_completions
from .config import (
    CACHE_HTTP_PORT,
    DEFAULT_MODEL,
    GENERATE_RETRY_COUNT,
    SUPPORTED_MODELS,
    URL_CACHE_ENABLED,
    USER_IMAGE_DIR,
    debug,
    get_api_key,
    get_base_url,
    model_selection_guide,
)
from .history import history_manager
from .utils import (
    extract_data_image_urls,
    extract_urls,
    ext_from_mime,
    is_likely_image_url,
    parse_data_image_url,
    replace_data_urls_with_local,
    wrap_bare_cache_images,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX = (
    "\n\n"
    "【默认规则】画面/字幕/标牌/海报/界面等任何可见文字默认使用简体中文；"
    "除非我在提示词里明确指定其他语言或多语言。"
)

# ---------------------------------------------------------------------------
# Tool descriptions
# ---------------------------------------------------------------------------


def _generate_desc() -> str:
    base = """生成图片。

参考图选择（内置SOP，按此执行）：
- 继续/再改/迭代/把上一张改成 → 使用历史底图：传 history_id（必要时先调用 history 搜索/定位）。
- 参考这张图生成/把这图变成 → 使用用户新图：传 use_latest_user_image=true。
- 文本里出现的图片链接/文件名/哈希 → 只当作历史线索；先 history(scope=recent, limit=10) 列出候选让用户选 history_id。

（当用户新上传图但意图是改历史图：底图用 history_id；新图内容由你看图提取后写进 prompt。）

输出要求：
- 调用后：把工具返回的图片链接使用 Markdown 图片格式粘贴到最终回复正文里。

参考图参数（三选一）：
- history_id：使用历史记录中的图片作为参考图（适合 继续/再改/迭代 等场景；配合 history 获取/搜索）
- image_url：使用外部图片 URL 作为参考图（适合 Agent/远程调用传入图片）
"""

    if USER_IMAGE_DIR is None:
        tail = """当前支持 history_id 和 image_url 作为参考图来源。

参数：
- model（必填）
- prompt（必填）
- history_id / image_url（可选；不填表示纯文本生成）
"""
    else:
        base += '- use_latest_user_image=true：使用用户最新上传图作为参考图（适合 新建/重绘/把这张图变成 等场景）\n'
        tail = """
参数：
- model（必填）
- prompt（必填）
- history_id / use_latest_user_image / image_url（可选；不填表示纯文本生成）
"""

    return base + "\n" + tail + "\n\n" + model_selection_guide()


HISTORY_DESC = """查看生成历史（跨会话混合累计）。

用途：搜索/定位 history_id（供 generate.history_id 使用）。

用法（内置SOP）：
- 当用户说 继续/上一张/再改改/把它加进去 等相对指代时：先列出 recent 候选让用户选 history_id，再 generate。

参数：
- history_id: 指定则只返回该条
- limit: 返回条数（默认 5）
- scope: recent / archive（默认 recent）"""


CACHE_DESC = """缓存/历史清理工具。

清理历史记录：include_history=true 且 confirm=true。

参数：
- action: status / clear / prune（默认 status）
- keep: prune 保留条数（默认 50）
- include_history: 是否同时清理/裁剪历史（默认 false）
- confirm: 删除历史记录确认开关（默认 false；仅 include_history=true 时生效）

注意：clear/prune 会删除本地文件（`mcp_server/url_cache/` 等）。"""

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def get_tools() -> list[Tool]:
    generate_properties: dict[str, object] = {
        "model": {
            "type": "string",
            "description": "模型名称（必须从枚举里选）",
            "enum": SUPPORTED_MODELS,
            "default": DEFAULT_MODEL,
        },
        "prompt": {
            "type": "string",
            "description": "生成描述（建议单段落：主体/场景/构图/光线/风格/细节）。",
        },
        "history_id": {
            "type": "integer",
            "description": "可选：稳定历史序号（在 history 列表中显示）；不会随列表变化",
        },
        "image_url": {
            "type": "string",
            "description": "可选：外部图片URL作为参考图（Agent/远程调用时使用；MCP会自动下载缓存）",
        },
    }

    if USER_IMAGE_DIR is not None:
        generate_properties["use_latest_user_image"] = {
            "type": "boolean",
            "default": False,
            "description": "可选：使用用户最新上传图作为参考图",
        }
        generate_properties["user_image_count"] = {
            "type": "integer",
            "default": 1,
            "description": "可选：使用最近几张用户图片（默认1，最多5）",
        }

    return [
        Tool(
            name="generate",
            description=_generate_desc(),
            inputSchema={
                "type": "object",
                "properties": generate_properties,
                "required": ["model", "prompt"],
            },
        ),
        Tool(
            name="history",
            description=HISTORY_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "history_id": {
                        "type": "integer",
                        "description": "可选：指定则只返回该条记录（稳定 history_id）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认5",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["recent", "archive"],
                        "default": "recent",
                        "description": "recent=短期历史，archive=长期归档（默认recent）",
                    },
                },
            },
        ),
        Tool(
            name="cache",
            description=CACHE_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "clear", "prune"],
                        "default": "status",
                        "description": "status=查看；clear=清空；prune=只保留最近N条",
                    },
                    "keep": {
                        "type": "integer",
                        "default": 50,
                        "description": "prune 时保留的条目数（默认50）",
                    },
                    "include_history": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否同时清理/裁剪历史记录",
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "删除历史记录需要显式确认",
                    },
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def handle_generate(args: dict[str, Any]) -> list[TextContent]:
    images: list[str] = []
    mcp_logs: list[str] = []
    used_history_ref = False

    model = str(args.get("model") or "").strip() or DEFAULT_MODEL

    # Validate: only one reference source
    ref_sources = 0
    if args.get("history_id") is not None:
        ref_sources += 1
    if args.get("use_latest_user_image"):
        ref_sources += 1
    if args.get("image_url"):
        ref_sources += 1
    if ref_sources > 1:
        return [TextContent(type="text", text="错误: 参考图来源只能三选一（history_id / use_latest_user_image / image_url），不允许同时提供多个。")]

    # User image import
    if args.get("use_latest_user_image"):
        try:
            count = min(int(args.get("user_image_count") or 1), 5)
            paths = pick_user_image_paths(count)
            local_urls: list[str] = []
            for p in paths:
                data_uri, local_url = await import_local_file(str(p))
                if data_uri:
                    images.append(data_uri)
                if local_url:
                    local_urls.append(local_url)
            if local_urls:
                names = ", ".join(p.name for p in paths)
                history_manager.add_success("user_image", f"user_image: {names}", local_urls)
            mcp_logs.append(f"参考图: 用户上传图 x{len(paths)}")
        except Exception as exc:
            return [TextContent(type="text", text=f"❌ 用户图片导入失败: {exc}")]

    # image_url reference
    if args.get("image_url"):
        image_url_val = str(args["image_url"]).strip()
        if not image_url_val.startswith(("http://", "https://")):
            return [TextContent(type="text", text="错误: image_url 必须是 http:// 或 https:// 开头的 URL")]
        mcp_logs.append(f"参考图: image_url={image_url_val[:80]}")
        b64 = await download_url_as_base64(image_url_val)
        if b64:
            images.append(b64)
            # Cache and record in history
            from .cache import store_local_media, ensure_cache_http_server, cache_url_media
            await cache_url_media(image_url_val)
            cached = get_cached_local_url(image_url_val)
            if cached:
                history_manager.add_success("image_url_import", f"image_url: {image_url_val[:100]}", [cached])
            mcp_logs.append("参考图: 下载成功")
        else:
            return [TextContent(type="text", text=f"❌ 无法下载参考图: {image_url_val[:200]}")]

    # Legacy parameter rejection
    if args.get("local_file"):
        return [TextContent(type="text", text="错误: 当前版本不支持 local_file；请使用 history_id / use_latest_user_image / image_url。")]
    if args.get("images"):
        return [TextContent(type="text", text="错误: 当前 MCP 不支持透传用户上传图片；请使用 history_id 或 image_url。")]

    # History reference
    if args.get("history_id") is not None:
        used_history_ref = True
        try:
            item_id = int(args.get("history_id"))
        except Exception:
            return [TextContent(type="text", text="错误: history_id 必须是整数")]

        mcp_logs.append(f"参考图: history_id={item_id}")
        history_item = history_manager.get_by_id(item_id, scope="archive")
        if history_item:
            urls_in_history = list(history_item.get("urls", []) or [])
            for url in urls_in_history:
                # Try local cache URL first (has extension), then try all URLs
                # (upstream URLs like Google Storage don't have image extensions)
                cached_url = get_cached_local_url(url)
                target = cached_url or url
                b64 = await download_url_as_base64(target)
                if b64:
                    images.append(b64)
                    break  # One reference image is enough
            mcp_logs.append(f"参考图数量: {len(images)}")
        else:
            mcp_logs.append("参考图: history_id 未找到")

    prompt = args.get("prompt", "")
    if not prompt:
        return [TextContent(type="text", text="错误: prompt 不能为空")]

    if used_history_ref and not images:
        return [TextContent(type="text", text=(
            "❌ 未能从该 history_id 获取到可用参考图。\n\n"
            "请先调用 `history`，确认该条记录里确实有图片结果，"
            "或改用 `use_latest_user_image=true` 提供参考图。"
        ))]

    # Model validation
    if model not in SUPPORTED_MODELS:
        suggestions = difflib.get_close_matches(model, SUPPORTED_MODELS, n=3, cutoff=0.2)
        hint = f"\n你可能想用: {', '.join(suggestions)}" if suggestions else ""
        return [TextContent(type="text", text=(
            f"错误: 不支持的 model: {model}{hint}\n"
            f"请从以下模型中选择: {', '.join(SUPPORTED_MODELS)}"
        ))]

    prompt_to_send = f"{prompt}{DEFAULT_IMAGE_TEXT_LANGUAGE_PROMPT_SUFFIX}"
    content: Any = prompt_to_send
    if images:
        content = [{"type": "text", "text": prompt_to_send}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})

    mcp_logs.append(f"模型: {model}")
    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]

    # Retry loop
    retry_count = max(0, min(int(GENERATE_RETRY_COUNT), 10))
    max_attempts = 1 + retry_count
    if retry_count > 0:
        mcp_logs.append(f"自动重试: {retry_count} 次（间隔 2s）")

    client = await http_client.get_client()
    base_url = get_base_url()
    api_key = get_api_key()
    first_error_summary = ""

    status = 0
    reasoning_text = ""
    content_text = ""
    err_text = ""

    for attempt in range(1, max_attempts + 1):
        mcp_logs.append(f"尝试: {attempt}/{max_attempts}")
        status, reasoning_text, content_text, err_text = await stream_chat_completions(
            client, base_url=base_url, api_key=api_key, model=model, messages=messages,
        )
        if attempt == 1:
            first_error_summary = (err_text.strip() or reasoning_text.strip() or "")[:500]
        if status == 200 and content_text.strip():
            mcp_logs.append("状态: 200 OK")
            break
        if status != 200:
            brief = (err_text.strip() or "")[:120].replace("\n", " ")
            mcp_logs.append(f"状态: HTTP {status}" + (f"（{brief}）" if brief else ""))
        else:
            mcp_logs.append("状态: 200 但无可用结果")
            if err_text.strip().startswith("empty content extracted"):
                break
        if attempt < max_attempts:
            mcp_logs.append("等待 2s 后重试")
            await asyncio.sleep(2)

    # Handle failure
    if status != 200 or not content_text.strip():
        summary = (err_text.strip() or first_error_summary or "无结果").strip()[:500]
        if summary.startswith("empty content extracted"):
            summary = "上游返回 200 但未返回可用结果字段。"
        error_msg = (
            f"❌ 生成失败：{summary}\n\n"
            "排查建议：\n"
            "- 检查 `FLOW2API_API_KEY` 是否正确/有权限\n"
            "- 确认模型名称是否可用/账号是否有配额\n"
            "- 尝试更换模型或检查上游服务状态\n"
        )
        history_manager.add_failure(model, prompt, summary)
        return [TextContent(type="text", text=error_msg)]

    # Process successful result
    urls = extract_urls(content_text)
    data_urls = extract_data_image_urls(content_text)
    mcp_logs.append(f"结果解析: urls={len(urls)}, data_urls={len(data_urls)}")

    # Store data: URIs locally
    data_url_map: dict[str, str] = {}
    stored_local_urls: list[str] = []
    for durl in data_urls:
        parsed = parse_data_image_url(durl)
        if not parsed:
            continue
        mime, raw = parsed
        filename = store_local_media(raw, mime=mime, ext=ext_from_mime(mime))
        if not filename:
            continue
        base = ensure_cache_http_server()
        local_url = f"{base}/mcp-cache/{filename}" if base else f"http://127.0.0.1:{CACHE_HTTP_PORT}/mcp-cache/{filename}"
        data_url_map[durl] = local_url
        stored_local_urls.append(local_url)

    # Record in history
    urls_to_record = list(urls)
    if stored_local_urls:
        urls_to_record.extend(stored_local_urls)
    history_manager.add_success(model, prompt, urls_to_record)

    # Cache upstream URLs
    cached_count = 0
    if URL_CACHE_ENABLED and urls:
        cached_count = await cache_urls(urls)
        mcp_logs.append(f"本机缓存: {cached_count}/{len(urls)}")

    # Render output
    rendered = content_text
    if data_url_map:
        rendered = replace_data_urls_with_local(rendered, data_url_map)
    rendered = replace_urls_with_cached(rendered, urls)
    rendered = wrap_bare_cache_images(rendered)

    if URL_CACHE_ENABLED:
        from .cache import _cache_http_base_url

        if _cache_http_base_url:
            mcp_logs.append(f"本机缓存地址: {_cache_http_base_url}")
        for u in stored_local_urls:
            try:
                fname = u.split("/mcp-cache/")[-1].split("?")[0]
                fpath = URL_CACHE_DIR / fname
                if fpath.exists():
                    mcp_logs.append(f"本地文件: {fpath.absolute()}")
            except Exception:
                pass
        for u in urls:
            local_url = get_cached_local_url(u)
            if local_url:
                try:
                    fname = local_url.split("/mcp-cache/")[-1].split("?")[0]
                    fpath = URL_CACHE_DIR / fname
                    if fpath.exists():
                        mcp_logs.append(f"本地文件: {fpath.absolute()}")
                except Exception:
                    pass

    final_text = rendered.strip() or "无结果"
    mcp_block = "\n".join(mcp_logs).strip() if mcp_logs else ""
    upstream_block = reasoning_text.strip()

    if mcp_block or upstream_block:
        sections: list[str] = []
        if mcp_block:
            sections.append("### MCP\n\n```text\n" + mcp_block + "\n```")
        if upstream_block:
            sections.append("### 上游\n\n```text\n" + upstream_block + "\n```")
        final_text = (
            "<details><summary>思考/日志</summary>\n\n"
            + "\n\n".join(sections)
            + "\n\n</details>\n\n"
            + final_text
        )

    return [TextContent(type="text", text=final_text)]


async def handle_history(args: dict[str, Any]) -> list[TextContent]:
    scope = str(args.get("scope") or "recent").strip() or "recent"
    if scope not in ("recent", "archive"):
        scope = "recent"
    limit = int(args.get("limit", 5) or 5)

    def _render_one(item: dict[str, Any], *, title: str) -> str:
        sizes = history_manager.sizes()
        lines: list[str] = [title, f"- 统计: recent={sizes['recent']}, archive={sizes['archive']}", ""]
        hid = item.get("id")
        hid_text = str(hid) if isinstance(hid, int) and hid > 0 else ""
        lines.append(f"## {hid_text}. {item.get('time', '')}")
        lines.append(f"- 模型: `{item.get('model', '')}`")
        lines.append(f"- 提示: {item.get('prompt', '')}")
        if item.get("error"):
            lines.append(f"- 状态: ❌ 失败 - {str(item.get('error'))[:500]}")
        else:
            urls = list(item.get("urls", []) or [])
            if urls:
                lines.append("- 结果:")
                for j, url in enumerate(urls, 1):
                    display_url = get_cached_local_url(url) or url
                    is_local = bool(get_cached_local_url(url)) or is_local_cache_url(url)
                    locality = "📦" if is_local else "🌐"
                    lines.append(f"  - {locality} ![history-{hid_text}-{j}]({display_url})")
            else:
                lines.append("- 状态: ⚠️ 成功但未提取到URL")
        lines.append("")
        return "\n".join(lines)

    if args.get("history_id") is not None:
        try:
            item_id = int(args.get("history_id"))
        except Exception:
            return [TextContent(type="text", text="错误: history_id 必须是整数")]
        item = history_manager.get_by_id(item_id, scope="archive") or history_manager.get_by_id(item_id, scope="recent")
        if not item:
            return [TextContent(type="text", text=f"未找到该 history_id: {item_id}")]
        return [TextContent(type="text", text=_render_one(item, title="# 生成历史（单条）"))]

    if args.get("query") is not None or args.get("keyword") is not None:
        return [TextContent(type="text", text=(
            "当前版本不支持关键词搜索。\n\n"
            "请改用：\n"
            "- `history { \"scope\": \"recent\", \"limit\": 10 }` 列出候选\n"
            "- 再用 `history { \"history_id\": 123 }` 精准查看"
        ))]

    if history_manager.is_empty(scope=scope):
        return [TextContent(type="text", text="暂无生成历史")]

    sizes = history_manager.sizes()
    lines: list[str] = [f"# 生成历史（{scope}）", f"- 统计: recent={sizes['recent']}, archive={sizes['archive']}", ""]
    items = history_manager.get_archive(limit) if scope == "archive" else history_manager.get_recent(limit)
    for i, h in enumerate(items, 1):
        hid = h.get("id")
        hid_text = str(hid) if isinstance(hid, int) and hid > 0 else str(i)
        lines.append(f"## {hid_text}. {h.get('time', '')}")
        lines.append(f"- 模型: `{h.get('model', '')}`")
        prompt = str(h.get("prompt", ""))
        lines.append(f"- 提示: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")
        if h.get("error"):
            lines.append(f"- 状态: ❌ 失败 - {str(h.get('error'))[:100]}")
        else:
            urls = list(h.get("urls", []) or [])
            if urls:
                lines.append("- 结果:")
                for j, url in enumerate(urls, 1):
                    display_url = get_cached_local_url(url) or url
                    is_local = bool(get_cached_local_url(url)) or is_local_cache_url(url)
                    locality = "📦" if is_local else "🌐"
                    lines.append(f"  - {locality} ![history-{i}-{j}]({display_url})")
            else:
                lines.append("- 状态: ⚠️ 成功但未提取到URL")
        lines.append("")
    return [TextContent(type="text", text="\n".join(lines))]


async def handle_cache(args: dict[str, Any]) -> list[TextContent]:
    action = str(args.get("action") or "status").strip() or "status"
    if action not in ("status", "clear", "prune"):
        action = "status"
    include_history = bool(args.get("include_history", False))
    confirm = bool(args.get("confirm", False))
    keep = int(args.get("keep", 50) or 50)

    if action == "status":
        sizes = history_manager.sizes()
        return [TextContent(type="text", text=(
            "# 缓存/历史状态\n\n"
            f"- url_cache_entries: {url_cache.size()}\n"
            f"- recent_history: {sizes['recent']}\n"
            f"- archive_history: {sizes['archive']}\n"
            f"- url_cache_dir: {URL_CACHE_DIR}\n"
        ))]

    if include_history and action in ("clear", "prune") and not confirm:
        sizes = history_manager.sizes()
        return [TextContent(type="text", text=(
            "⚠️ 该操作将删除历史记录，但未提供确认参数。\n\n"
            f"当前统计：url_cache={url_cache.size()}, recent={sizes['recent']}, archive={sizes['archive']}\n\n"
            f"请增加 `confirm=true` 确认执行。"
        ))]

    if action == "clear":
        cache_removed = url_cache.size()
        url_cache.clear_all()
        history_removed = history_manager.clear_all() if include_history else {"recent_removed": 0, "archive_removed": 0}
        return [TextContent(type="text", text=(
            "# 已清理\n\n"
            f"- url_cache_removed: {cache_removed}\n"
            f"- history_recent_removed: {history_removed['recent_removed']}\n"
            f"- history_archive_removed: {history_removed['archive_removed']}\n"
        ))]

    # prune
    cache_removed = url_cache.prune_to(keep)
    history_removed = history_manager.prune_to(keep) if include_history else {"recent_removed": 0, "archive_removed": 0}
    return [TextContent(type="text", text=(
        "# 已裁剪\n\n"
        f"- keep: {keep}\n"
        f"- url_cache_removed: {cache_removed}\n"
        f"- history_recent_removed: {history_removed['recent_removed']}\n"
        f"- history_archive_removed: {history_removed['archive_removed']}\n"
    ))]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


def apply_prompt_template(template: str, arguments: dict[str, str] | None) -> str:
    if not arguments:
        return template
    out = template
    for k, v in arguments.items():
        out = out.replace("{{" + str(k) + "}}", str(v))
    return out


PROMPTS: dict[str, dict[str, Any]] = {
    "flow2api_reference_sop": {
        "title": "Reference SOP (Base vs Element)",
        "description": "参考图选择与冲突处理（Base vs Element），用于稳定连续改图流程。",
        "arguments": [],
        "template": (
            "你已接入 MCP：flow2api（generate/history/cache）。\n\n"
            "参考图选择（Base vs Element）：\n"
            "- 工具只接收 1 张参考图（Base）。\n"
            "- 额外的新上传图/外链图视为素材（Element）：由你看图提取关键元素，用文字写进 prompt。\n\n"
            "调用规则：\n"
            "1) 新建/重绘 -> generate(use_latest_user_image=true)。\n"
            "2) 迭代修改 -> generate(history_id=...)；不知道 ID 先 history 列出候选。\n"
            "3) 冲突场景：用户新上传图+改历史图 -> Base=history_id；新图关键元素写入 prompt。\n"
            "4) 文本里出现图片链接/文件名/哈希：只当作历史线索，不当作参考图传给上游。\n\n"
            "输出要求：\n"
            "- generate 返回后，把图片链接以 Markdown 形式粘贴到最终正文。\n"
            "- cache 清理历史需要 include_history=true 且 confirm=true。\n"
        ),
    },
    "flow2api_prompt_builder": {
        "title": "Prompt Builder",
        "description": "把用户意图改写为单段落生成提示词（主体/场景/构图/光线/风格/细节）。",
        "arguments": [
            PromptArgument(
                name="user_request",
                description="用户原始需求（会被你改写成生成 prompt）",
                required=True,
            )
        ],
        "template": (
            "将下列用户需求改写为适合图片生成模型的单段落提示词。\n"
            "要求：主体、场景、构图/镜头、光线、风格、细节；画面内可见文字默认简体中文（除非用户指定）。\n\n"
            "用户需求：\n{{user_request}}\n"
        ),
    },
    "flow2api_troubleshoot_generate": {
        "title": "Troubleshoot Generate Failures",
        "description": "生成失败时的最小排查清单与下一步动作建议。",
        "arguments": [
            PromptArgument(
                name="error",
                description="工具/上游返回的错误信息（可直接粘贴）",
                required=True,
            )
        ],
        "template": (
            "你正在排查一次 generate 失败。\n\n"
            "先输出 4 行信息：\n"
            "1) model=...\n"
            "2) reference=history_id/use_latest_user_image/none\n"
            "3) prompt_summary=...\n"
            "4) error={{error}}\n\n"
            "然后给出下一步建议：\n"
            "- 若是 401/403：检查 API Key/权限/配额。\n"
            "- 若是 400：缩短 prompt、检查模型名、检查参考图是否存在。\n"
            "- 若无结果：提示用户开启本机缓存，并建议换模型重试。\n"
        ),
    },
}
