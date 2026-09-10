"""Gemini provider — Google's Gemini API via the official ``google-genai`` SDK.

Isolated in this module; the rest of the application only knows
``LLMProvider``. Configuration comes from environment variables:

    LLM_PROVIDER=gemini
    GEMINI_API_KEY=...
    GEMINI_MODEL=gemini-2.5-flash   # optional; this is the default

Function/tool calling: the model receives OpenAPI-style function declarations
and answers with ``function_call`` parts; tool results are fed back as
``function_response`` parts. The final structured answer is requested with
JSON response mime type where the model accepts it; correctness is always
enforced by the orchestrator's Pydantic validation, never by trusting the
provider.

The SDK client can be injected (``client=``) so unit tests run without the
package or network.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import LLMConfigurationError, LLMError
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
)

_DEFAULT_MODEL = "gemini-flash-latest"  # alias tracking the current GA flash model
_REQUEST_TIMEOUT_MS = 120_000  # 2 minutes per completion
_TRANSIENT_RETRIES = 3  # extra attempts for 429/503 (free-tier demand spikes)
_RETRY_BACKOFF_SECONDS = 2.0  # 2s, 4s, 8s


def _lazy_import():
    try:
        from google import genai
        from google.genai import types

        return genai, types
    except ImportError as exc:  # pragma: no cover — only without the package
        raise LLMConfigurationError(
            "The google-genai package is not installed. "
            "Run: pip install google-genai"
        ) from exc


def _to_gemini_contents(
    messages: list[LLMMessage],
    types: Any,
) -> list[Any]:
    """Map the neutral conversation to Gemini Content objects.

    Gemini has two roles: "user" and "model". Assistant tool requests become
    ``function_call`` parts (role "model"); tool results become
    ``function_response`` parts (role "user"). Gemini correlates responses by
    function *name*, so the provider tracks the tool_call_id -> name mapping
    from the preceding assistant message.
    """
    contents: list[Any] = []
    id_to_name: dict[str, str] = {}

    for msg in messages:
        if msg.role == "system":
            continue  # handled via config.system_instruction
        if msg.role == "assistant":
            if msg.tool_calls:
                id_to_name.update({tc.id: tc.name for tc in msg.tool_calls})
                parts = []
                for tc in msg.tool_calls:
                    signature = (tc.metadata or {}).get("thought_signature")
                    part_kwargs: dict[str, Any] = {
                        "function_call": types.FunctionCall(
                            name=tc.name, args=dict(tc.arguments or {})
                        )
                    }
                    if signature is not None:
                        # Gemini 3 requires thought signatures to round-trip
                        # with the function call parts it produced.
                        part_kwargs["thought_signature"] = signature
                    parts.append(types.Part(**part_kwargs))
                contents.append(types.Content(role="model", parts=parts))
            elif msg.content:
                contents.append(
                    types.Content(role="model", parts=[types.Part(text=msg.content)])
                )
        elif msg.role == "tool":
            name = id_to_name.get(msg.tool_call_id or "", "tool")
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=name,
                                response={"result": msg.content or ""},
                            )
                        )
                    ],
                )
            )
        else:  # user
            contents.append(
                types.Content(role="user", parts=[types.Part(text=msg.content or "")])
            )
    return contents


def _to_function_declarations(tools: list[ToolSpec], types: Any) -> list[Any]:
    return [
        types.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters=t.parameters,
        )
        for t in tools
    ]


class GeminiLLMProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.2,
        *,
        client: Any = None,
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "GEMINI_API_KEY is not set. Set it in the environment "
                "(or backend/.env) or switch LLM_PROVIDER to 'mock' for "
                "offline/demo mode."
            )
        self._model = model or _DEFAULT_MODEL
        self._temperature = temperature
        if client is not None:
            self._client = client
        else:
            genai, types = _lazy_import()
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
            )

    # ---------------- public API ----------------
    def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        types = _lazy_types()
        system_prompt = next(
            (m.content for m in messages if m.role == "system" and m.content), None
        )
        contents = _to_gemini_contents(messages, types)

        tool_config: dict[str, Any] = {}
        if tools:
            tool_config["tools"] = [
                types.Tool(function_declarations=_to_function_declarations(tools, types))
            ]

        base_config: dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": self._temperature,
            **tool_config,
        }

        # Prefer JSON output mode for the structured final answer. Some model
        # versions reject combining it with function declarations — retry
        # without it rather than failing the run.
        attempts: list[dict[str, Any]] = [dict(base_config)]
        if response_format and tools:
            json_config = dict(base_config)
            json_config["response_mime_type"] = "application/json"
            attempts.insert(0, json_config)

        last_error: Exception | None = None
        for index, config_kwargs in enumerate(attempts):
            try:
                response = self._attempt_with_transient_retries(
                    contents, config_kwargs, types
                )
            except _sdk_client_error_type() as exc:
                # Non-transient client error (e.g. JSON mime unsupported by
                # this model) — try the next config if one exists.
                last_error = exc
                if index < len(attempts) - 1:
                    continue
                break
            except Exception as exc:  # noqa: BLE001 — mapped, never escapes
                last_error = exc
                break
            if response is not None:
                return self._map_response(response)

        raise LLMError(f"Gemini request failed: {_summarize(last_error)}")

    def _attempt_with_transient_retries(
        self, contents: list[Any], config_kwargs: dict[str, Any], types: Any
    ) -> Any:
        """Run one completion attempt, retrying transient 429/503 failures.

        Free-tier Gemini endpoints occasionally answer 503 UNAVAILABLE during
        demand spikes; a short bounded backoff makes the agent resilient
        without masking real errors.
        """
        import time

        last_error: Exception | None = None
        client_error_type = _sdk_client_error_type()
        server_error_type = _sdk_server_error_type()
        for attempt in range(_TRANSIENT_RETRIES + 1):
            try:
                return self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            except (client_error_type, server_error_type) as exc:
                code = getattr(exc, "code", None)
                transient = code in (429, 503)
                last_error = exc
                if transient and attempt < _TRANSIENT_RETRIES:
                    time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise
        raise last_error if last_error else LLMError("Gemini request failed")

    # ---------------- response mapping ----------------
    def _map_response(self, response: Any) -> LLMResponse:
        """Map a Gemini response, pairing each function call with the thought
        signature on its part (Gemini 3 requires it to be echoed back)."""
        tool_calls: list[ToolCall] = []
        index = 0
        try:
            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                parts = getattr(getattr(candidate, "content", None), "parts", None) or []
                for part in parts:
                    fc = getattr(part, "function_call", None)
                    if fc is None:
                        continue
                    args = dict(getattr(fc, "args", None) or {})
                    call_id = getattr(fc, "id", None) or f"gem_call_{index + 1}"
                    metadata: dict[str, Any] = {}
                    signature = getattr(part, "thought_signature", None)
                    if signature is not None:
                        metadata["thought_signature"] = signature
                    tool_calls.append(
                        ToolCall(
                            id=str(call_id), name=str(fc.name), arguments=args,
                            metadata=metadata,
                        )
                    )
                    index += 1
        except Exception:
            pass
        return LLMResponse(content=_extract_text(response), tool_calls=tool_calls)


# ---------------- module helpers ----------------
def _lazy_types():
    from google.genai import types  # local import: keeps tests SDK-free

    return types


def _sdk_client_error_type():
    try:
        from google.genai import errors as genai_errors

        return genai_errors.ClientError
    except ImportError:  # pragma: no cover — only without the package
        return type("_Never", (Exception,), {})


def _sdk_server_error_type():
    try:
        from google.genai import errors as genai_errors

        return genai_errors.ServerError
    except ImportError:  # pragma: no cover — only without the package
        return type("_Never", (Exception,), {})


def _extract_text(response: Any) -> str | None:
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            parts = getattr(getattr(candidate, "content", None), "parts", None) or []
            texts = [p.text for p in parts if getattr(p, "text", None)]
            if texts:
                return "".join(texts)
    except Exception:
        return None
    return None


def _summarize(error: Exception | None) -> str:
    if error is None:
        return "unknown error"
    code = getattr(error, "code", None)
    message = str(error)[:300]
    suffix = f" (HTTP {code})" if code else ""
    return f"{type(error).__name__}{suffix}: {message}"