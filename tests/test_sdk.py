from types import SimpleNamespace

import pytest
from copilot.generated.session_events import (
    AssistantMessageDeltaData,
    AssistantUsageData,
)

from market_intelligence.models import SignalBatch
from market_intelligence.providers import CopilotProvider


async def test_sdk_uses_typed_sessions_selected_model_and_no_tools(tmp_path):
    expected = SignalBatch.model_validate(
        {
            "signals": [
                {
                    "evidence_id": "ev-test",
                    "observation": "test",
                    "quote": "test",
                    "limitations": [],
                }
            ]
        }
    )
    kwargs = {}

    class Session:
        session_id = "sdk-test"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def send_and_wait_typed(self, prompt, response_type, *, timeout):
            assert "payload" in prompt
            assert response_type is SignalBatch
            assert timeout == 30
            kwargs["on_event"](SimpleNamespace(data=AssistantMessageDeltaData("x", "msg")))
            kwargs["on_event"](
                SimpleNamespace(
                    data=AssistantUsageData(model="actual-model", input_tokens=20, output_tokens=10)
                )
            )
            return expected

    class Client:
        async def create_session(self, **options):
            kwargs.update(options)
            return Session()

    provider = CopilotProvider(tmp_path)
    provider.client = Client()
    result = await provider.generate(
        "call", "inputs", "Required skill", {"payload": "test"}, SignalBatch, "chosen-model", 30
    )
    assert result == expected
    assert kwargs["model"] == "chosen-model"
    assert kwargs["available_tools"] == []
    assert kwargs["enable_config_discovery"] is False
    assert kwargs["enable_session_store"] is False
    assert "Required skill" in kwargs["system_message"]["content"]
    assert provider.metrics[0].effective_models == ["actual-model"]
    assert provider.metrics[0].input_tokens == 20
    assert provider.metrics[0].first_token_seconds is not None
    assert provider.metrics[0].session_id == "sdk-test"


async def test_invalid_model_is_not_silently_substituted(tmp_path):
    class Client:
        async def get_auth_status(self):
            return SimpleNamespace(isAuthenticated=True)

        async def list_models(self):
            return [SimpleNamespace(to_dict=lambda: {"id": "allowed"})]

    provider = CopilotProvider(tmp_path)
    provider.client = Client()
    with pytest.raises(ValueError, match="not available"):
        await provider.validate_models({"not-allowed"})
