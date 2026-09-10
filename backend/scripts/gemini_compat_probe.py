"""Minimal isolated Gemini multi-turn function-calling compatibility probe.

COMPLETELY separate from GitPilot production logic: it imports only the
installed ``google-genai`` SDK (plus GitPilot's tool/provider classes for
the optional bisect phases, without modifying them). The API key is read
from backend/.env or the environment and is NEVER printed.

Purpose: determine why the deployed agent still receives HTTP 500 from
Gemini after several successful tool rounds, and whether the failure is
model-specific (gemini-3.1-flash-lite), schema-specific (GitPilot's real
tool declarations), or provider-mapping-specific (GeminiLLMProvider).

Phases, run per model:

  A  TRIVIAL    two trivial tools, SDK-native history (exact Content
                objects appended as returned) — the Google-documented flow.
  B  SCHEMAS    GitPilot's REAL tool declarations + SDK-native history.
                Succeeding here while GitPilot fails live implicates
                GitPilot's history reconstruction; failing here implicates
                a real tool schema.
  C  PROVIDER   GitPilot's actual GeminiLLMProvider.complete() driven
                end-to-end against the live API (real client injected).
                Succeeding here while GitPilot fails live implicates
                something about the production conversation/prompt shape,
                not the provider mapping itself.

Flow per phase: user request -> tool call -> tool result -> second tool
call -> tool result -> final response. No retries anywhere.

Usage (from backend/):
    python scripts/gemini_compat_probe.py                    # default models
    python scripts/gemini_compat_probe.py gemini-3.1-flash-lite gemini-flash-latest
"""
from __future__ import annotations

import json
import os
import sys

from google import genai
from google.genai import types

MAX_TURNS = 6  # far more than the 3 requests each phase needs

# ---------------------------------------------------------------------------
# Scenario shared by all phases: two trivial tools whose second call depends
# on the first call's result (forces genuine sequential multi-turn calling).
# ---------------------------------------------------------------------------
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_popular_movie",
        description="Return the most popular movie currently showing in a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    ),
    types.FunctionDeclaration(
        name="get_movie_showtime",
        description="Return the next showtime for one movie in a city.",
        parameters={
            "type": "object",
            "properties": {
                "movie": {"type": "string", "description": "Movie title"},
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["movie", "city"],
        },
    ),
]
TRIVIAL_TOOLS = [types.Tool(function_declarations=TOOL_DECLARATIONS)]

FAKE_RESULTS = {
    "get_popular_movie": {"movie": "Dune: Part Two"},
    "get_movie_showtime": {"showtime": "19:30", "theater": "Tokyo Cinema 1"},
}

USER_TASK = (
    "Find out which movie is currently most popular in Tokyo, then tell me "
    "the next showtime for that movie in Tokyo. Use the provided tools."
)

DEFAULT_MODELS = [
    "gemini-3.1-flash-lite",  # current production model — reproduce first
    "gemini-flash-latest",    # best available alias as the alternative
]


def load_api_key() -> str | None:
    """Read GEMINI_API_KEY from backend/.env or the environment. Never printed."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key.strip()
    env_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    )
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
    return None


def describe_signature(part: types.Part) -> str:
    sig = getattr(part, "thought_signature", None)
    if sig is None:
        return "no signature"
    size = len(sig) if isinstance(sig, (bytes, str)) else -1
    unit = "bytes" if isinstance(sig, bytes) else "chars"
    return f"signature present ({size} {unit})"


def print_parts(parts: list) -> None:
    for index, part in enumerate(parts):
        if part.function_call:
            fc = part.function_call
            print(
                f"    part[{index}]: function_call {fc.name}("
                f"{dict(fc.args or {})}) id={fc.id!r} {describe_signature(part)}"
            )
        elif part.text is not None:
            kind = "THOUGHT text" if getattr(part, "thought", False) else "text"
            print(f"    part[{index}]: {kind}: {part.text[:100]!r} {describe_signature(part)}")


# ---------------------------------------------------------------------------
# Phase A: trivial tools, SDK-native history
# ---------------------------------------------------------------------------
def run_trivial_probe(client: genai.Client, model: str) -> bool:
    print(f"\n{'=' * 72}\nPHASE A — trivial tools, SDK-native history ({model})\n{'=' * 72}")
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=USER_TASK)])
    ]
    for turn in range(1, MAX_TURNS + 1):
        print(f"--- REQUEST {turn}: sending {len(contents)} content(s) ---")
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(tools=TRIVIAL_TOOLS),
            )
        except Exception as exc:  # noqa: BLE001 — probe reports, never retries
            print(f"!!! REQUEST {turn} FAILED: {type(exc).__name__} (HTTP {getattr(exc, 'code', None)})")
            print(f"    message: {str(exc)[:300]}")
            return False
        candidate = response.candidates[0] if response.candidates else None
        content = candidate.content if candidate else None
        parts = list(getattr(content, "parts", None) or [])
        function_calls = [p.function_call for p in parts if p.function_call]
        print(f"--- RESPONSE {turn}: {len(parts)} part(s) ---")
        print_parts(parts)
        if not function_calls:
            print(f"\n>>> FINAL RESULT: {response.text!r}")
            print(f">>> Phase A: SUCCESS after {turn} request(s)")
            return True
        # SDK-native history: append the exact model Content, then results.
        contents.append(content)
        fr_parts = []
        for part in parts:
            fc = part.function_call
            if fc is None:
                continue
            kwargs = {"name": fc.name, "response": {"result": FAKE_RESULTS.get(fc.name, {"status": "ok"})}}
            if fc.id:
                kwargs["id"] = fc.id
            fr_parts.append(types.Part(function_response=types.FunctionResponse(**kwargs)))
        contents.append(types.Content(role="user", parts=fr_parts))
        print(f"    -> appended exact model Content + {len(fr_parts)} function_response part(s)")
    print(f">>> Phase A: INCOMPLETE within {MAX_TURNS} turns")
    return False


# ---------------------------------------------------------------------------
# Phase B: GitPilot's real tool declarations + SDK-native history
# ---------------------------------------------------------------------------
def build_real_declarations():
    """GitPilot's actual GitHub tool declarations (schemas only; no network).

    A mock transport serves every GitHub request with one stub JSON body —
    tools never execute here, only their declarations are sent.
    """
    # Make the backend root importable regardless of how the script is run
    # (script mode puts scripts/ first on sys.path, where a different 'app'
    # module from site-packages would shadow backend/app).
    backend_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    import httpx
    from app.services.github_service import GitHubService
    from app.tools.github_tools import build_github_tools

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"default_branch": "main", "full_name": "acme/demo"}))
    github = GitHubService(token="probe-token", transport=transport)
    return build_github_tools(github, max_output_chars=2000)


GITHUB_TASK = (
    "Investigate issue #1 of repository Rahul-252506/gitpilot-demo: first "
    "retrieve the issue, then find where login is handled by searching the "
    "repository. Use the provided tools."
)


def run_real_schema_probe(client: genai.Client, model: str, tools) -> bool:
    print(f"\n{'=' * 72}\nPHASE B — GitPilot real tool schemas, SDK-native history ({model})\n{'=' * 72}")
    declarations = [
        types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.parameters)
        for t in tools
    ]
    print(f"Using GitPilot's {len(declarations)} real tool declarations: {', '.join(d.name for d in declarations)}")
    stub = types.Tool(function_declarations=declarations)
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=GITHUB_TASK)])
    ]
    for turn in range(1, MAX_TURNS + 1):
        print(f"--- REQUEST {turn}: sending {len(contents)} content(s) ---")
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(tools=[stub]),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"!!! REQUEST {turn} FAILED: {type(exc).__name__} (HTTP {getattr(exc, 'code', None)})")
            print(f"    message: {str(exc)[:300]}")
            return False
        candidate = response.candidates[0] if response.candidates else None
        content = candidate.content if candidate else None
        parts = list(getattr(content, "parts", None) or [])
        function_calls = [p.function_call for p in parts if p.function_call]
        print(f"--- RESPONSE {turn}: {len(parts)} part(s) ---")
        print_parts(parts)
        if not function_calls:
            print(f"\n>>> FINAL RESULT: {response.text!r}")
            print(f">>> Phase B: SUCCESS after {turn} request(s)")
            return True
        contents.append(content)
        fr_parts = []
        for part in parts:
            fc = part.function_call
            if fc is None:
                continue
            result = {"status": "ok", "stub": True, "tool": fc.name}
            kwargs = {"name": fc.name, "response": {"result": json.dumps(result)}}
            if fc.id:
                kwargs["id"] = fc.id
            fr_parts.append(types.Part(function_response=types.FunctionResponse(**kwargs)))
        contents.append(types.Content(role="user", parts=fr_parts))
        print(f"    -> appended exact model Content + {len(fr_parts)} function_response part(s)")
    print(f">>> Phase B: INCOMPLETE within {MAX_TURNS} turns")
    return False


# ---------------------------------------------------------------------------
# Phase C: GitPilot's actual GeminiLLMProvider driven against the live API
# ---------------------------------------------------------------------------
def run_provider_probe(client: genai.Client, model: str, tools) -> bool:
    print(f"\n{'=' * 72}\nPHASE C — GitPilot GeminiLLMProvider.complete() end-to-end ({model})\n{'=' * 72}")
    backend_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from app.services.llm.base import LLMMessage, ToolSpec
    from app.services.llm.gemini_provider import GeminiLLMProvider

    specs = [ToolSpec(name=t.name, description=t.description, parameters=t.parameters) for t in tools]
    provider = GeminiLLMProvider(api_key="unused-injected", model=model, client=client)
    messages = [LLMMessage(role="user", content=GITHUB_TASK)]
    for turn in range(1, MAX_TURNS + 1):
        print(f"--- complete() call {turn}: {len(messages)} message(s) in context ---")
        try:
            response = provider.complete(messages, specs)
        except Exception as exc:  # noqa: BLE001
            print(f"!!! complete() {turn} FAILED: {type(exc).__name__}")
            print(f"    message: {str(exc)[:300]}")
            return False
        if response.wants_tool_call:
            for tc in response.tool_calls:
                sig = (tc.metadata or {}).get("thought_signature")
                size = len(sig) if isinstance(sig, (bytes, str)) else 0
                print(f"    -> tool_call {tc.name} id={tc.id!r} signature={'yes (%d)' % size if size else 'NO'}")
            messages.append(LLMMessage(role="assistant", content=response.content, tool_calls=response.tool_calls))
            for tc in response.tool_calls:
                result = json.dumps({"status": "ok", "stub": True, "tool": tc.name})
                messages.append(LLMMessage(role="tool", tool_call_id=tc.id, content=result))
            continue
        print(f"\n>>> FINAL RESULT: {response.content!r}")
        print(f">>> Phase C: SUCCESS after {turn} complete() call(s)")
        return True
    print(f">>> Phase C: INCOMPLETE within {MAX_TURNS} calls")
    return False


# ---------------------------------------------------------------------------
def main() -> int:
    key = load_api_key()
    if not key:
        print("ERROR: GEMINI_API_KEY not found in backend/.env or environment.")
        return 2

    try:
        import google.genai as _g

        sdk_version = getattr(_g, "__version__", "unknown")
    except Exception:  # pragma: no cover
        sdk_version = "unknown"
    print(f"google-genai SDK version: {sdk_version}")
    print(f"API key loaded: yes (length {len(key)}, value not shown)")

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=90_000))

    models = sys.argv[1:] or list(DEFAULT_MODELS)

    try:
        available = sorted(m.name for m in client.models.list())
        print(f"\nModels available to this key ({len(available)} total). Requested:")
        for wanted in models:
            status = "available" if any(wanted in name for name in available) else "NOT LISTED (may still work)"
            print(f"    {wanted!r}: {status}")
    except Exception as exc:  # noqa: BLE001
        print(f"models.list() failed (continuing anyway): {type(exc).__name__}: {str(exc)[:200]}")

    real_tools = None
    try:
        real_tools = build_real_declarations()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not build GitPilot real tools (phases B/C skipped): {type(exc).__name__}: {str(exc)[:200]}")

    verdict: dict[str, dict[str, bool]] = {}
    for model in models:
        verdict[model] = {
            "A trivial/SDK-native": run_trivial_probe(client, model),
        }
        if real_tools is not None:
            verdict[model]["B real-schemas/SDK-native"] = run_real_schema_probe(client, model, real_tools)
            verdict[model]["C real provider end-to-end"] = run_provider_probe(client, model, real_tools)

    print(f"\n{'=' * 72}\nVERDICT\n{'=' * 72}")
    for model, phases in verdict.items():
        for phase, ok in phases.items():
            print(f"    {model:<26} {phase:<28} {'SUCCESS' if ok else 'FAILED'}")

    for model, phases in verdict.items():
        a, b = phases.get("A trivial/SDK-native"), phases.get("B real-schemas/SDK-native")
        c = phases.get("C real provider end-to-end")
        if a and b and c:
            print(f"\n{model}: fully healthy across all phases.")
        elif a and not b:
            print(f"\n{model}: trivial flow OK but a REAL TOOL SCHEMA breaks it — inspect declarations.")
        elif a and b and c is False:
            print(f"\n{model}: SDK-native flow OK but GeminiLLMProvider mapping breaks it — inspect _to_gemini_contents/_map_response.")
        elif not a:
            print(f"\n{model}: even the trivial documented flow fails — model/API-level issue.")
    return 0 if all(ok for phases in verdict.values() for ok in phases.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
