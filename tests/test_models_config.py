from __future__ import annotations

import importlib
import json


def test_load_models_config_respects_custom_models_json(tmp_path):
    import mcp_server.config as config_module

    config_module = importlib.reload(config_module)
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default_model": "custom-fast",
                "models": ["custom-fast", "custom-quality"],
                "selection_guide": "只显示我自己挑的模型",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    models, default_model, selection_guide = config_module._load_models_config(models_path)

    assert models == ["custom-fast", "custom-quality"]
    assert default_model == "custom-fast"
    assert selection_guide == "只显示我自己挑的模型"
