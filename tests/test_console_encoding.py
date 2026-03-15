from __future__ import annotations


class _DummyStream:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_force_utf8_console_reconfigures_stdout_and_stderr(monkeypatch):
    import mcp_server.console_encoding as console_encoding

    stdout = _DummyStream()
    stderr = _DummyStream()
    monkeypatch.setattr(console_encoding.sys, "stdout", stdout)
    monkeypatch.setattr(console_encoding.sys, "stderr", stderr)

    console_encoding.force_utf8_console()

    expected = [{"encoding": "utf-8", "errors": "replace"}]
    assert stdout.calls == expected
    assert stderr.calls == expected


def test_force_utf8_console_ignores_streams_without_reconfigure(monkeypatch):
    import mcp_server.console_encoding as console_encoding

    monkeypatch.setattr(console_encoding.sys, "stdout", object())
    monkeypatch.setattr(console_encoding.sys, "stderr", object())

    console_encoding.force_utf8_console()
