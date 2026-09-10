"""Unit tests for the Gemini provider — no network, SDK client faked.

The fake client mimics only the surface the provider uses:
``client.models.generate_content(model=..., contents=..., config=...)``.
"""
from __future__ import annotations

import base64
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
    """JSON response mime type is used ONLY on tools-free structured calls.

    Combining JSON mime with function declarations makes current Gemini
    models (e.g. gemini-3.1-flash-lite) fail with HTTP 500 INTERNAL, so the
    two modes are never mixed: tool turns use plain function calling; the
    final structured turn uses JSON mode without tools. If the model still
    rejects JSON mode there, one plain-config retry follows.
    """

    def test_tool_turn_does_not_force_json_mime(self):
        """Tool-calling requests must not send response_mime_type at all."""
        provider, client = make_provider([make_response(text="{}")])
        provider.complete(sample_messages(), SAMPLE_TOOLS, response_format={"type": "json_object"})
        assert len(client.models.calls) == 1  # single attempt, no fallback loop
        config = client.models.calls[0]["config"]
        assert config.response_mime_type is None
        assert config.tools[0].function_declarations[0].name == "get_issue"

    def test_structured_tools_free_turn_uses_json_mime(self):
        """The final report request (no tools) gets JSON mode."""
        provider, client = make_provider([make_response(text="{}")])
        provider.complete(sample_messages(), [], response_format={"type": "json_object"})
        config = client.models.calls[0]["config"]
        assert config.response_mime_type == "application/json"
        assert not config.tools

    def test_json_mime_rejected_retries_without_it(self):
        """If the model rejects JSON mode on the structured turn, one plain
        retry follows instead of failing the run."""
        client = FakeClient([
            genai_errors.ClientError(400, {"message": "response_mime_type not supported"}),
            make_response(text="{}"),
        ])
        provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
        response = provider.complete(sample_messages(), [], response_format={"type": "json_object"})
        assert response.content == "{}"
        assert len(client.models.calls) == 2
        assert client.models.calls[0]["config"].response_mime_type == "application/json"
        assert client.models.calls[1]["config"].response_mime_type is None

    def test_400_without_json_format_requested_fails_immediately(self):
        client = FakeClient([
            genai_errors.ClientError(400, {"message": "bad"}),
        ])
        provider = GeminiLLMProvider(api_key="fake", model="gemini-test", client=client)
        with pytest.raises(LLMError):
            provider.complete(sample_messages(), SAMPLE_TOOLS)
        assert len(client.models.calls) == 1


class TestMultiTurnHistoryReconstruction:
    """Regression tests for the Gemini 3 multi-turn history reconstruction.

    Live failure: after two successful tool rounds, the NEXT multi-turn
    request failed. Root causes found: (a) FunctionCall.id was stripped from
    replayed history while Gemini 3 pairs calls with responses by id — two
    same-name calls (e.g. get_file twice) become ambiguous; (b) the model's
    visible text for a tool-call turn was dropped. These tests pin the exact
    required round-trip: user → FC+signature → tool result → FC+signature →
    tool result → continuation.
    """

    # Real API thought signatures are base64-encoded blobs; the SDK's Part
    # model validates the encoding, so tests must use realistic values.
    SIG_A = base64.b64encode(b"signature-a").decode()
    SIG_B = base64.b64encode(b"signature-b").decode()

    @staticmethod
    def _fc_response(name, call_id, signature, args=None, text=None):
        """A fake Gemini response: one function-call part (with API-issued id
        and thought signature) plus an optional visible text part."""
        parts = [
            SimpleNamespace(
                function_call=gtypes.FunctionCall(name=name, args=args or {"q": "auth"}, id=call_id),
                text=None,
                thought_signature=signature,
                thought=False,
            )
        ]
        if text is not None:
            parts.append(SimpleNamespace(text=text, thought_signature=None, thought=False))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])

    def test_full_two_round_signature_round_trip(self):
        """user → FC+sig → tool → FC+sig → tool → continuation: every id and
        signature must survive every mapping step."""
        client = FakeClient([
            self._fc_response("get_issue", "fc_1", TestMultiTurnHistoryReconstruction.SIG_A, args={"owner": "acme"}),
            self._fc_response("get_file", "fc_2", TestMultiTurnHistoryReconstruction.SIG_B, args={"path": "auth.py"}, text="Checking auth.py next."),
            make_response(text="continuation answer"),
        ])
        provider = GeminiLLMProvider(api_key="fake", model="m", client=client)
        spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
        msgs = [
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content="task"),
        ]

        # Round 1: model calls get_issue with signature SIG_A.
        r1 = provider.complete(msgs, [spec])
        assert r1.tool_calls[0].id == "fc_1"
        assert r1.tool_calls[0].metadata["thought_signature"] == TestMultiTurnHistoryReconstruction.SIG_A
        msgs.append(LLMMessage(role="assistant", content=None, tool_calls=r1.tool_calls))
        msgs.append(LLMMessage(role="tool", tool_call_id="fc_1", content="issue body"))

        # Round 2: model calls get_file with signature SIG_B (same session).
        r2 = provider.complete(msgs, [spec])
        assert r2.tool_calls[0].id == "fc_2"
        assert r2.tool_calls[0].metadata["thought_signature"] == TestMultiTurnHistoryReconstruction.SIG_B
        assert r2.content == "Checking auth.py next."
        msgs.append(LLMMessage(role="assistant", content=r2.content, tool_calls=r2.tool_calls))
        msgs.append(LLMMessage(role="tool", tool_call_id="fc_2", content="file contents"))

        # Round 3: continuation succeeds and the history it saw is intact.
        r3 = provider.complete(msgs, [spec])
        assert r3.content == "continuation answer"
        history = client.models.calls[2]["contents"]
        parts = [(c.role, p) for c in history for p in c.parts]
        fc_parts = [p for _, p in parts if getattr(p, "function_call", None)]
        assert [p.function_call.id for p in fc_parts] == ["fc_1", "fc_2"]
        # The SDK normalizes signature strings to bytes; compare decoded.
        assert [base64.b64encode(p.thought_signature).decode() for p in fc_parts] == [
            TestMultiTurnHistoryReconstruction.SIG_A,
            TestMultiTurnHistoryReconstruction.SIG_B,
        ]
        assert [p.function_call.name for p in fc_parts] == ["get_issue", "get_file"]

    def test_second_request_history_is_structurally_valid(self):
        """Capture the ACTUAL contents of the request after two tool rounds:
        every FunctionCall carries its API-issued id + signature, every
        FunctionResponse carries the matching id, and the model's visible
        text is preserved in its turn."""
        client = FakeClient([
            self._fc_response("get_issue", "fc_1", TestMultiTurnHistoryReconstruction.SIG_A),
            self._fc_response("get_file", "fc_2", TestMultiTurnHistoryReconstruction.SIG_B, text="Now reading auth.py."),
            make_response(text="done"),
        ]
        )
        provider = GeminiLLMProvider(api_key="fake", model="m", client=client)
        spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
        msgs = [LLMMessage(role="user", content="task")]
        for _ in range(2):
            r = provider.complete(msgs, [spec])
            msgs.append(LLMMessage(role="assistant", content=r.content, tool_calls=r.tool_calls))
            msgs.append(LLMMessage(role="tool", tool_call_id=r.tool_calls[0].id, content="result"))
        provider.complete(msgs, [spec])  # third request: history must be valid

        contents = client.models.calls[2]["contents"]
        model_contents = [c for c in contents if c.role == "model"]
        user_contents = [c for c in contents if c.role == "user"]
        # Locate FC/FR parts structurally (turn 2's model content is
        # [text_part, fc_part], so positional indexing would be wrong).
        fc_parts = [p for c in model_contents for p in c.parts if getattr(p, "function_call", None)]
        fr_parts = [p.function_response for c in user_contents for p in c.parts if getattr(p, "function_response", None)]
        assert len(fc_parts) == 2 and len(fr_parts) == 2
        fc1, fc2 = fc_parts
        fr1, fr2 = fr_parts
        # Ids survive on both sides of each pair (required for pairing).
        assert fc1.function_call.id == "fc_1" and fr1.id == "fc_1"
        assert fc2.function_call.id == "fc_2" and fr2.id == "fc_2"
        # Signatures stay on their own FC parts (SDK stores bytes).
        assert base64.b64encode(fc1.thought_signature).decode() == TestMultiTurnHistoryReconstruction.SIG_A
        assert base64.b64encode(fc2.thought_signature).decode() == TestMultiTurnHistoryReconstruction.SIG_B
        # The second turn's visible text was preserved, not dropped.
        texts = [p.text for c in model_contents for p in c.parts if getattr(p, "text", None)]
        assert texts == ["Now reading auth.py."]
        # FR responses carry the tool output.
        assert fr1.response == {"result": "result"}
        assert fr2.response == {"result": "result"}

    def test_synthetic_ids_never_sent_to_api(self):
        """When the API issues no function-call id, our synthetic id is used
        internally but NEITHER the replayed FC nor the FR carries an id —
        both sides omit it consistently so pairing stays valid."""
        client = FakeClient([
            self._fc_response("get_issue", None, TestMultiTurnHistoryReconstruction.SIG_A),
            make_response(text="done"),
        ])
        provider = GeminiLLMProvider(api_key="fake", model="m", client=client)
        spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
        msgs = [LLMMessage(role="user", content="task")]
        r1 = provider.complete(msgs, [spec])
        assert r1.tool_calls[0].id.startswith("gem_call_")  # synthetic
        msgs.append(LLMMessage(role="assistant", content=None, tool_calls=r1.tool_calls))
        msgs.append(LLMMessage(role="tool", tool_call_id=r1.tool_calls[0].id, content="res"))
        provider.complete(msgs, [spec])

        contents = client.models.calls[1]["contents"]
        fc_part = next(p for c in contents if c.role == "model" for p in c.parts if getattr(p, "function_call", None))
        fr_part = next(p.function_response for c in contents if c.role == "user" for p in c.parts if getattr(p, "function_response", None))
        assert fc_part.function_call.id is None  # synthetic id not leaked to API
        assert fr_part.id is None  # both sides omit consistently

    def test_thought_parts_excluded_from_extracted_text(self):
        """Thought parts (chain-of-thought) never surface as response text."""
        parts = [
            SimpleNamespace(text="internal reasoning...", thought=True, thought_signature=None),
            SimpleNamespace(text=None, function_call=gtypes.FunctionCall(name="t", args={}), thought_signature=None, thought=False),
        ]
        resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])
        provider, _ = make_provider([resp])
        spec = ToolSpec(name="t", description="d", parameters={"type": "object", "properties": {}})
        response = provider.complete([LLMMessage(role="user", content="x")], [spec])
        assert response.content is None  # thought text excluded
        assert response.wants_tool_call


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
