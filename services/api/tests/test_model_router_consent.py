import asyncio

import pytest

from app.core.model_router import ModelRouter


def _blocked_router() -> ModelRouter:
    return ModelRouter(
        model_config={
            "cloud_consent": False,
            "primary": {
                "provider_id": "qwen",
                "base_url": "https://example.invalid/v1",
                "api_key": "test-key",
                "model": "test-model",
            },
        }
    )


def test_explicitly_denied_cloud_consent_blocks_sync_call() -> None:
    with pytest.raises(RuntimeError, match="Cloud processing consent is required"):
        _blocked_router().chat_text(user="paper content")


def test_explicitly_denied_cloud_consent_blocks_async_call() -> None:
    with pytest.raises(RuntimeError, match="Cloud processing consent is required"):
        asyncio.run(_blocked_router().achat_text(user="paper content"))


def test_legacy_config_keeps_implicit_server_compatibility() -> None:
    router = ModelRouter(model_config={"primary": {"provider_id": "qwen"}})

    assert router.cloud_consent is None
    assert router.provider_info("primary")["provider_id"] == "qwen"
