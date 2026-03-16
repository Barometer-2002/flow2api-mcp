from __future__ import annotations

import asyncio
import importlib


def _tool_map():
    import mcp_server.tools as tools_module

    tools_module = importlib.reload(tools_module)
    return {tool.name: tool for tool in tools_module.get_tools()}, tools_module


def test_generate_description_includes_reference_decision_rules():
    tools, _tools_module = _tool_map()

    generate_tool = tools["generate"]
    description = generate_tool.description or ""
    schema = generate_tool.inputSchema or {}

    assert "先判断当前任务属于哪一类" in description
    assert "必填只有 model 和 prompt" in description
    assert "纯文本生成" in description
    assert "先调用 history" in description
    assert "不要猜测 history_id" in description
    assert "只能有一个有效参考图来源" in description
    assert "0 / 空字符串 / false 会视为未传" in description
    assert "不要再套 params" in description
    assert "不要额外塞其他字段" in description
    assert "文本里出现的图片链接/文件名/哈希" in description
    assert schema["required"] == ["model", "prompt"]
    assert schema["additionalProperties"] is False
    assert "user_image_count" not in schema["properties"]


def test_history_and_cache_descriptions_include_call_guardrails():
    tools, _tools_module = _tool_map()

    history_description = tools["history"].description or ""
    cache_description = tools["cache"].description or ""

    assert "不知道 history_id 就先列 recent 候选" in history_description
    assert "不要凭空猜测 history_id" in history_description
    assert "默认不要调用 cache" in cache_description
    assert "只有用户明确要求查看/清理缓存" in cache_description


def test_reference_and_troubleshoot_prompts_include_misuse_guardrails():
    _tools, tools_module = _tool_map()

    reference_template = tools_module.PROMPTS["flow2api_reference_sop"]["template"]
    troubleshoot_template = tools_module.PROMPTS["flow2api_troubleshoot_generate"]["template"]

    assert "不要猜测 history_id" in reference_template
    assert "先调用 history" in reference_template
    assert "不要同时传多个参考图来源" in reference_template
    assert "只把新图内容提炼进 prompt" in reference_template

    assert "先检查是否同时传了多个有效参考图来源" in troubleshoot_template
    assert "不要猜测 history_id" in troubleshoot_template
    assert "相对指代" in troubleshoot_template


def test_generate_rejects_unexpected_extra_fields(monkeypatch):
    import mcp_server.tools as tools_module

    tools_module = importlib.reload(tools_module)

    result = asyncio.run(
        tools_module.handle_generate(
            {
                "model": "gemini-3.1-flash-image-landscape",
                "prompt": "test",
                "params": {"foo": "bar"},
            }
        )
    )

    assert result
    assert "只接受这 5 个扁平字段" in result[0].text
    assert "不要再套 params" in result[0].text
