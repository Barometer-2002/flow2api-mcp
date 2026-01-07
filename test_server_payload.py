import asyncio
import base64
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


import mcp_server.server as server


class TestGeneratePayload(unittest.TestCase):
    """Regression tests for upstream parsing + MCP tool behavior.

    Run:
        python -m unittest -q
    """
    def test_openai_stream_parsing_ignores_empty_choices(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield 'data: {"choices": []}'
                yield 'data: {"choices":[{"delta":{"content":"hi"}}]}'
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertEqual(content, "hi")
        self.assertEqual(err, "")

    def test_openai_stream_parses_data_without_space(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield 'data:{"choices":[{"delta":{"content":"hi"}}]}'
                yield "data:[DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertEqual(content, "hi")
        self.assertEqual(err, "")

    def test_openai_nonstream_message_content_parsed(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield '{"choices":[{"message":{"content":"hello"}}]}'

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertEqual(content, "hello")
        self.assertEqual(err, "")

    def test_openai_stream_parses_image_url_parts(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield (
                    'data: {"choices":[{"delta":{"content":['
                    '{"type":"text","text":"ok"},'
                    '{"type":"image_url","image_url":{"url":"http://example.com/a.png"}}'
                    ']}}]}'
                )
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertIn("ok", content)
        self.assertIn("http://example.com/a.png", content)
        self.assertEqual(err, "")

    def test_openai_stream_parses_delta_images_array(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield (
                    'data: {"choices":[{"delta":{"images":[{"url":"data:image/png;base64,aGVsbG8="}]}}]}'
                )
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertIn("data:image/png;base64,", content)
        self.assertEqual(err, "")

    def test_openai_stream_parses_delta_images_array_with_image_url_object(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield (
                    'data: {"choices":[{"delta":{"images":[{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,aGVsbG8="}}]}}]}'
                )
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertIn("data:image/jpeg;base64,", content)
        self.assertEqual(err, "")

    def test_openai_nonstream_parses_message_images_array(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield (
                    '{"choices":[{"message":{"images":[{"url":"data:image/png;base64,aGVsbG8="}]}}]}'
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertIn("data:image/png;base64,", content)
        self.assertEqual(err, "")

    def test_openai_stream_empty_content_returns_diagnostics(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{}}]}'
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertEqual(content, "")
        self.assertIn("empty content extracted", err)
        self.assertIn("choice0_keys=", err)

    def test_openai_stream_parses_delta_images_single_object(self) -> None:
        class FakeResponse:
            status_code = 200

            async def aread(self):
                return b""

            async def aiter_lines(self):
                yield (
                    'data: {"choices":[{"delta":{"images":{"url":"data:image/png;base64,aGVsbG8="}}}]}'
                )
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        status, reasoning, content, err = asyncio.run(
            server._flow2api_stream_chat_completions(
                FakeClient(), base_url="http://x", api_key="k", model="m", messages=[{"role": "user", "content": "x"}]
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(reasoning, "")
        self.assertIn("data:image/png;base64,", content)
        self.assertEqual(err, "")

    def test_history_id_without_image_asks_for_more_precise_info(self) -> None:
        async def fail_flow2api(*_args, **_kwargs):
            raise AssertionError("should not call upstream when history_id has no images")

        with (
            patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
            patch.object(server.history_manager, "get_by_id", return_value={"urls": ["http://example.com/a.mp4"]}),
            patch.object(server, "_flow2api_stream_chat_completions", new=fail_flow2api),
        ):
            result = asyncio.run(
                server.handle_generate(
                    {
                        "model": "gemini-2.5-flash-image-landscape",
                        "prompt": "make an image",
                        "history_id": 123,
                    }
                )
            )

    def test_generate_does_not_retry_on_empty_parsing(self) -> None:
        async def empty_parse(*_args, **_kwargs):
            return 200, "", "", "empty content extracted; events=1, json=1, choices=1"

        async def fail_sleep(_seconds: float):
            raise AssertionError("should not sleep/retry on empty parsing")

        with (
            patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
            patch.object(server, "_flow2api_stream_chat_completions", new=empty_parse),
            patch.object(server.asyncio, "sleep", new=fail_sleep),
        ):
            result = asyncio.run(
                server.handle_generate(
                    {
                        "model": server.DEFAULT_MODEL,
                        "prompt": "x",
                    }
                )
            )
            self.assertEqual(len(result), 1)
            self.assertIn("empty content extracted", result[0].text)

    def test_history_local_cache_url_marked_as_cached(self) -> None:
        local = "http://127.0.0.1:46262/mcp-cache/x.jpg"
        item = {"id": 1, "time": "t", "model": "m", "prompt": "p", "urls": [local], "error": None}
        with (
            patch.object(server, "URL_CACHE_ENABLED", False),
            patch.object(server.history_manager, "is_empty", return_value=False),
            patch.object(server.history_manager, "sizes", return_value={"recent": 1, "archive": 1}),
            patch.object(server.history_manager, "get_recent", return_value=[item]),
        ):
            result = asyncio.run(server.handle_history({"scope": "recent", "limit": 5}))
            self.assertTrue(result)
            self.assertIn("📦", result[0].text)
            self.assertIn(local, result[0].text)

    def test_history_by_id_returns_single_item(self) -> None:
        item = {
            "id": 123,
            "time": "t",
            "model": "m",
            "prompt": "p",
            "urls": ["http://127.0.0.1:46262/mcp-cache/x.jpg"],
            "error": None,
        }
        with (
            patch.object(server, "URL_CACHE_ENABLED", False),
            patch.object(server.history_manager, "sizes", return_value={"recent": 1, "archive": 1}),
            patch.object(server.history_manager, "get_by_id", return_value=item),
        ):
            result = asyncio.run(server.handle_history({"history_id": 123}))
            self.assertTrue(result)
            self.assertIn("# 生成历史（单条）", result[0].text)
            self.assertIn("## 123.", result[0].text)
            self.assertIn("![history-123-1]", result[0].text)

    def test_history_query_not_supported(self) -> None:
        result = asyncio.run(server.handle_history({"query": "x", "scope": "recent"}))
        self.assertTrue(result)
        self.assertIn("不支持关键词搜索", result[0].text)

    def test_import_local_file_uri_copies_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create a fake png file.
            src_dir = os.path.join(tmp, "CherryStudio", "Data", "Files")
            os.makedirs(src_dir, exist_ok=True)
            src_path = os.path.join(src_dir, "upload.png")
            raw = b"fakepng"
            with open(src_path, "wb") as f:
                f.write(raw)

            cache_dir = os.path.join(tmp, "mcp_cache")
            cache_index = os.path.join(tmp, "url_cache.json")

            file_uri = "file:///" + src_path.replace("\\", "/")

            with (
                patch.object(server, "USER_IMAGE_DIR", server.Path(src_dir)),
                patch.object(server, "URL_CACHE_DIR", server.Path(cache_dir)),
                patch.object(server, "URL_CACHE_INDEX_FILE", server.Path(cache_index)),
                patch.object(server, "_ensure_cache_http_server", return_value="http://127.0.0.1:46262"),
            ):
                # Reset cache state for this test.
                server.url_cache._loaded = True
                server.url_cache._index = {}

                data_uri, local_url = asyncio.run(server._import_local_file(file_uri))
                self.assertTrue(data_uri and data_uri.startswith("data:image/png;base64,"))
                self.assertTrue(local_url and "/mcp-cache/" in local_url)

                decoded = base64.b64decode(data_uri.split(",", 1)[1])
                self.assertEqual(decoded, raw)

                # The file should be copied into URL_CACHE_DIR
                self.assertTrue(os.path.isdir(cache_dir))
                self.assertTrue(any(name.endswith(".png") for name in os.listdir(cache_dir)))

    def test_use_latest_user_image_picks_newest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = server.Path(tmp)
            old_path = root / "old.jpg"
            new_path = root / "new.png"
            old_path.write_bytes(b"old")
            new_path.write_bytes(b"new")

            now = 1_700_000_000
            os.utime(old_path, (now - 200, now - 200))
            os.utime(new_path, (now - 10, now - 10))

            async def fake_flow2api(_client, *, model, messages, **_kwargs):
                content = messages[0]["content"]
                self.assertIsInstance(content, list)
                # newest file should be used
                url = content[1]["image_url"]["url"]
                self.assertTrue(url.startswith("data:image/png;base64,"))
                decoded = base64.b64decode(url.split(",", 1)[1])
                self.assertEqual(decoded, b"new")
                return 200, "", "ok", ""

            with (
                patch.object(server, "USER_IMAGE_DIR", root),
                patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
                patch.object(server.history_manager, "add_success", return_value=None),
                patch.object(server, "_flow2api_stream_chat_completions", new=fake_flow2api),
                patch.object(server, "_ensure_cache_http_server", return_value="http://127.0.0.1:46262"),
            ):
                asyncio.run(
                    server.handle_generate(
                        {
                            "model": "gemini-2.5-flash-image-landscape",
                            "prompt": "x",
                            "use_latest_user_image": True,
                        }
                    )
                )

    def test_history_manager_assigns_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history_file = server.Path(tmp) / "history.json"
            archive_file = server.Path(tmp) / "history_archive.json"

            with (
                patch.object(server, "HISTORY_FILE", history_file),
                patch.object(server, "HISTORY_ARCHIVE_FILE", archive_file),
                patch.object(server, "MAX_HISTORY_RECENT_SIZE", 50),
                patch.object(server, "MAX_HISTORY_ARCHIVE_SIZE", 2000),
            ):
                hm = server.HistoryManager()
                hm.add_success("m1", "p1", ["u1"])
                hm.add_failure("m2", "p2", "err")

                a = hm.get_archive(10)[::-1]  # chronological
                self.assertEqual(int(a[0]["id"]), 1)
                self.assertEqual(int(a[1]["id"]), 2)
                self.assertIsNotNone(hm.get_by_id(1, scope="archive"))
                self.assertIsNotNone(hm.get_by_id(2, scope="archive"))

                # Reload should keep ids
                hm2 = server.HistoryManager()
                b = hm2.get_archive(10)[::-1]
                self.assertEqual(int(b[0]["id"]), 1)
                self.assertEqual(int(b[1]["id"]), 2)

    def test_load_models_config_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = server.Path(tmp) / "models.json"
            p.write_text(
                '{\n  "default_model": "m2",\n  "models": ["m1", "m2"],\n  "selection_guide_lines": ["g1", "g2"]\n}\n',
                encoding="utf-8",
            )
            models, default_model, guide = server._load_models_config(p)
            self.assertEqual(models, ["m1", "m2"])
            self.assertEqual(default_model, "m2")
            self.assertEqual(guide, "g1\ng2")

    def test_video_i2v_uses_history_image_urls(self) -> None:
        history_url = "http://example.com/a.jpg"
        data_uri = "data:image/jpeg;base64,Zm9v"

        async def fake_download(url: str):
            self.assertEqual(url, history_url)
            return data_uri

        async def fake_flow2api(_client, *, model, messages, **_kwargs):
            self.assertEqual(model, "veo_3_1_i2v_s_fast_fl_landscape")

            self.assertEqual(len(messages), 1)
            content = messages[0]["content"]
            self.assertIsInstance(content, list)
            self.assertEqual(content[1]["type"], "image_url")
            self.assertEqual(content[1]["image_url"]["url"], data_uri)

            return 200, "", "ok", ""

        with (
            patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
            patch.object(server.history_manager, "get_by_id", return_value={"urls": [history_url]}),
            patch.object(server.history_manager, "add_success", return_value=None),
            patch.object(server, "download_url_as_base64", new=fake_download),
            patch.object(server, "_flow2api_stream_chat_completions", new=fake_flow2api),
            patch.object(server, "URL_CACHE_ENABLED", False),
        ):
            result = asyncio.run(
                server.handle_generate(
                    {
                        "model": "veo_3_1_i2v_s_fast_fl_landscape",
                        "prompt": "make a video",
                        "history_id": 1,
                    }
                )
            )
            self.assertTrue(result)

    def test_img2img_uses_data_uri_images(self) -> None:
        history_url = "http://example.com/a.jpg"
        data_uri = "data:image/jpeg;base64,Zm9v"

        async def fake_download(url: str):
            self.assertEqual(url, history_url)
            return data_uri

        async def fake_flow2api(_client, *, model, messages, **_kwargs):
            self.assertEqual(model, "gemini-2.5-flash-image-landscape")

            content = messages[0]["content"]
            self.assertIsInstance(content, list)
            self.assertEqual(content[1]["image_url"]["url"], data_uri)
            return 200, "", "ok", ""

        with (
            patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
            patch.object(server.history_manager, "get_by_id", return_value={"urls": [history_url]}),
            patch.object(server.history_manager, "add_success", return_value=None),
            patch.object(server, "download_url_as_base64", new=fake_download),
            patch.object(server, "_flow2api_stream_chat_completions", new=fake_flow2api),
            patch.object(server, "URL_CACHE_ENABLED", False),
        ):
            result = asyncio.run(
                server.handle_generate(
                    {
                        "model": "gemini-2.5-flash-image-landscape",
                        "prompt": "make an image",
                        "history_id": 1,
                    }
                )
            )
            self.assertTrue(result)

    def test_reference_source_must_be_single_choice(self) -> None:
        image_model = "gemini-2.5-flash-image-landscape"

        with (
            patch.object(server, "USER_IMAGE_DIR", server.Path("C:/allowed")),
            patch.object(server.history_manager, "get_by_id", return_value={"urls": ["http://example.com/a.jpg"]}),
            patch.object(server, "download_url_as_base64", new=AsyncMock(return_value="data:image/jpeg;base64,Zm9v")),
            patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
            patch.object(server, "_flow2api_stream_chat_completions", new=AsyncMock(return_value=(200, "", "ok", ""))),
            patch.object(server, "_pick_latest_user_image_path", return_value=server.Path("C:/allowed/x.png")),
            patch.object(server, "_import_local_file", new=AsyncMock(return_value=("data:image/png;base64,Zm9v", "http://127.0.0.1:46262/mcp-cache/x.png"))),
        ):
            result = asyncio.run(
                server.handle_generate(
                    {
                        "model": image_model,
                        "prompt": "x",
                        "history_id": 1,
                        "use_latest_user_image": True,
                    }
                )
            )
            self.assertTrue(result)
            self.assertIn("二选一", result[0].text)

    def test_generate_wraps_video_url_as_markdown_link(self) -> None:
        video_url = "http://example.com/a.mp4"
        video_model = "veo_3_1_t2v_fast_landscape"

        async def fake_flow2api(_client, *, model, messages, **_kwargs):
            self.assertEqual(model, video_model)
            self.assertEqual(messages[0]["role"], "user")
            return 200, "", f"video: {video_url}", ""

        with (
            patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
            patch.object(server.history_manager, "add_success", return_value=None),
            patch.object(server, "_flow2api_stream_chat_completions", new=fake_flow2api),
            patch.object(server, "SUPPORTED_MODELS", [video_model]),
        ):
            result = asyncio.run(
                server.handle_generate(
                    {
                        "model": video_model,
                        "prompt": "make a video",
                    }
                )
            )
            self.assertTrue(result)
            self.assertIn(f"[video]({video_url})", result[0].text)

    def test_generate_stores_data_image_url_and_returns_local_link(self) -> None:
        data_url = "data:image/png;base64,ZmFrZXBuZw=="  # base64("fakepng")
        image_model = server.SUPPORTED_MODELS[0]

        async def fake_flow2api(_client, *, model, messages, **_kwargs):
            self.assertEqual(model, image_model)
            return 200, "", data_url, ""

        recorded = {}

        def fake_add_success(model, prompt, urls):
            recorded["urls"] = list(urls)

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = server.Path(tmp) / "url_cache"
            cache_index = server.Path(tmp) / "url_cache.json"

            with (
                patch.object(server.http_client, "get_client", new=AsyncMock(return_value=None)),
                patch.object(server, "_flow2api_stream_chat_completions", new=fake_flow2api),
                patch.object(server, "URL_CACHE_DIR", cache_dir),
                patch.object(server, "URL_CACHE_INDEX_FILE", cache_index),
                patch.object(server, "_ensure_cache_http_server", return_value="http://127.0.0.1:46262"),
                patch.object(server.history_manager, "add_success", side_effect=fake_add_success),
            ):
                result = asyncio.run(
                    server.handle_generate(
                        {"model": image_model, "prompt": "x"}
                    )
                )
                self.assertTrue(result)
                self.assertIn("http://127.0.0.1:46262/mcp-cache/", result[0].text)
                # History should store local URL, not the data URL.
                self.assertTrue(any(u.startswith("http://127.0.0.1:46262/mcp-cache/") for u in recorded.get("urls", [])))

    def test_cache_clear_with_include_history_requires_confirm(self) -> None:
        with (
            patch.object(server.history_manager, "sizes", return_value={"recent": 3, "archive": 4}),
            patch.object(server.url_cache, "size", return_value=7),
        ):
            result = asyncio.run(
                server.handle_cache(
                    {
                        "action": "clear",
                        "include_history": True,
                    }
                )
            )
            self.assertTrue(result)
            self.assertIn("confirm", result[0].text)
            self.assertIn("include_history", result[0].text)

    def test_url_cache_load_prunes_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = server.Path(tmp)
            cache_dir = tmp_path / "url_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            exists_path = cache_dir / "a.png"
            exists_path.write_bytes(b"x")

            index_file = tmp_path / "url_cache.json"
            import json

            index_file.write_text(
                json.dumps(
                    {
                        "ok": {"path": str(exists_path), "mime": "image/png", "time": 1},
                        "missing": {"path": str(cache_dir / "missing.png"), "mime": "image/png", "time": 2},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            uc = server.UrlCache()
            with (
                patch.object(server, "URL_CACHE_DIR", cache_dir),
                patch.object(server, "URL_CACHE_INDEX_FILE", index_file),
            ):
                uc._load()
                self.assertIn("ok", uc._index)
                self.assertNotIn("missing", uc._index)


class TestPrompts(unittest.TestCase):
    def test_list_prompts_contains_expected_names(self) -> None:
        prompts = asyncio.run(server.list_prompts())
        names = {p.name for p in prompts}
        self.assertIn("flow2api_reference_sop", names)
        self.assertIn("flow2api_prompt_builder", names)
        self.assertIn("flow2api_troubleshoot_generate", names)

    def test_get_prompt_renders_template(self) -> None:
        result = asyncio.run(
            server.get_prompt("flow2api_prompt_builder", {"user_request": "把这张图改成水墨画"})
        )
        self.assertTrue(result.messages)
        content = result.messages[0].content
        self.assertEqual(content.type, "text")
        self.assertIn("把这张图改成水墨画", content.text)


if __name__ == "__main__":
    unittest.main()
