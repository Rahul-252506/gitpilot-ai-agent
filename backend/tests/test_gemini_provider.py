"""Unit tests for the Gemini provider — no network, SDK client faked.

The fake client mimics only the surface the provider uses:
``client.models.generate_content(model=..., contents=..., config=...)``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from google.genai import types as gtypes

from app.core.errors import LLMConfigurationError, LLMError
from app.services.llm.gemini_provider import GeminiLLMProvider
from app.services.llm.base import LLMMessage, ToolCall, ToolSpec

GET_ISSUE_SPEC = ToolSpec(
    name="get_issue",
    description="Retrieve a GitHub issue",
    parameters={
        "type": "object",
        "properties": {
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "issue_number": {"type": "integer"},
        },
        "required": ["owner", "repo", "issue_number"],
    },
)


def make_response(function_calls=None, text=None):
    """Build a fake GenerateContentResponse-shaped object."""
    parts = []
    if text is not None:
        parts.append(SimpleNamespace(text=text))
    for fc in function_calls or []:
        parts.append(SimpleNamespace(function_call=fc, text=None))
    candidate = SimpleNamespace(content=SimpleNamespace(parts=parts))
    return SimpleNamespace(candidates=[candidate], function_calls=function_calls or [])


class FakeModels:
    """Scripted SDK stand-in: pops responses in order; when the script runs
    dry it repeats the last response, modelling a persistent error across
    transient-retry attempts."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self._last: Any = None
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs) -> Any:
        self.calls.append(kwargs)
        if self._responses:
            self._last = self._responses.pop(0)
        item = self._last
        if item is None:
            raise AssertionError("fake client had no scripted responses")
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.models = FakeModels(responses)


def make_provider(responses: list[Any]) -> tuple[GeminiLLMProvider, FakeClient]:
    client = FakeClient(responses)
    provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
    return provider, client


SAMPLE_TOOLS = [GET_ISSUE_SPEC]


def sample_messages() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="You are GitPilot."),
        LLMMessage(role="user", content="Investigate acme/demo #1."),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_1", name="get_issue", arguments={"owner": "acme"})],
        ),
        LLMMessage(role="tool", tool_call_id="call_1", content="Issue #1 text"),
    ]


class TestConstruction:
    def test_missing_api_key_raises_configuration_error(self):
        with pytest.raises(LLMConfigurationError):
            GeminiLLMProvider(api_key="")

    def test_injected_client_is_used(self):
        provider, client = make_provider([make_response(text="ok")])
        assert provider._client is client


class TestRequestMapping:
    def test_system_prompt_and_tool_declarations_passed(self):
        provider, client = make_provider([make_response(text="{}")])
        provider.complete(sample_messages(), SAMPLE_TOOLS, response_format={"type": "json_object"})
        config = client.models.calls[0]["config"]
        assert config.system_instruction == "You are GitPilot."
        decl = config.tools[0].function_declarations[0]
        assert decl.name == "get_issue"
        assert decl.description == "Retrieve a GitHub issue"
        # The SDK normalizes the plain-JSON parameters dict into a Schema.
        params = decl.parameters.model_dump(exclude_none=True)
        assert params["required"] == ["owner", "repo", "issue_number"]
        assert client.models.calls[0]["model"] == "gemini-test"

    def test_assistant_tool_calls_map_to_function_call_parts(self):
        provider, client = make_provider([make_response(text="{}")])
        provider.complete(sample_messages(), SAMPLE_TOOLS)
        contents = client.models.calls[0]["contents"]
        roles = [c.role for c in contents]
        assert roles == ["user", "model", "user"]  # system excluded
        model_call = contents[1].parts[0].function_call
        assert model_call.name == "get_issue"
        assert model_call.args == {"owner": "acme"}

    def test_tool_result_maps_to_function_response_with_name(self):
        provider, client = make_provider([make_response(text="{}")])
        provider.complete(sample_messages(), SAMPLE_TOOLS)
        contents = client.models.calls[0]["contents"]
        fr = contents[2].parts[0].function_response
        assert fr.name == "get_issue"  # resolved from tool_call_id
        assert fr.response == {"result": "Issue #1 text"}


class TestResponseMapping:
    def test_function_calls_mapped_to_tool_calls(self):
        fc = gtypes.FunctionCall(name="search_repository", args={"query": "login"})
        provider, _ = make_provider([make_response(function_calls=[fc])])
        response = provider.complete(sample_messages(), SAMPLE_TOOLS)
        assert response.wants_tool_call
        assert response.tool_calls[0].name == "search_repository"
        assert response.tool_calls[0].arguments == {"query": "login"}
        assert response.tool_calls[0].id  # synthetic id generated

    def test_text_only_response_mapped(self):
        provider, _ = make_provider([make_response(text='{"issue_summary": "x"}')])
        response = provider.complete(sample_messages(), SAMPLE_TOOLS)
        assert not response.wants_tool_call
        assert response.content == '{"issue_summary": "x"}'


class TestJsonModeFallback:
    def test_400_with_json_mime_retries_without_it(self):
        client = FakeClient([
            genai_errors.ClientError(400, {"message": "response_mime_type not supported with tools"}),
            make_response(text="{}"),
        ])
        provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
        response = provider.complete(sample_messages(), SAMPLE_TOOLS, response_format={"type": "json_object"})
        assert response.content == "{}"
        assert len(client.models.calls) == 2
        first_config = client.models.calls[0]["config"]
        second_config = client.models.calls[1]["config"]
        assert first_config.response_mime_type == "application/json"
        assert second_config.response_mime_type is None

    def test_400_without_json_format_requested_fails_immediately(self):
        client = FakeClient([
            genai_errors.ClientError(400, {"message": "bad"}),
        ])
        provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
        with pytest.raises(LLMError):
            provider.complete(sample_messages(), SAMPLE_TOOLS)
        assert len(client.models.calls) == 1


class TestErrorMapping:
    def test_api_error_becomes_llm_error(self):
        client = FakeClient([genai_errors.ClientError(429, {"message": "quota exceeded"})])
        provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
        with pytest.raises(LLMError) as excinfo:
            provider.complete(sample_messages(), SAMPLE_TOOLS)
        assert "429" in str(excinfo.value)

    def test_unexpected_error_becomes_llm_error(self):
        client = FakeClient([RuntimeError("connection reset")])
        provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
        with pytest.raises(LLMError):
            provider.complete(sample_messages(), SAMPLE_TOOLS)

    def test_error_message_never_contains_api_key(self):
        client = FakeClient([genai_errors.ClientError(403, {"message": "denied"})])
        provider = GeminiLLMProvider(api_key="super-secret-key-value", model="gemini-test", client=client)
        with pytest.raises(LLMError) as excinfo:
            provider.complete(sample_messages(), SAMPLE_TOOLS)
        assert "super-secret-key-value" not in str(excinfo.value)
