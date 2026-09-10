"""Tool registry: central discovery + safe execution.

Execution safety: argument validation happens inside each tool, handlers
run under a timeout, exceptions become structured ToolResults, and every
result is re-bounded to ``max_output_chars`` before it can reach the model.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any

from app.services.llm.base import ToolSpec
from app.tools.base import Tool, ToolError, ToolResult
from app.tools.truncation import truncate


class ToolRegistry:
    def __init__(self, tools: list[Tool], max_output_chars: int = 8000) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self.max_output_chars = max_output_chars

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.to_spec() for t in self._tools.values()]

    def is_write(self, name: str) -> bool:
        tool = self._tools.get(name)
        return bool(tool and tool.is_write)

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                summary="Unknown tool",
                error=f"Unknown tool: {name}. Available tools: {', '.join(self.names())}",
            )

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(tool.handler, arguments)
                try:
                    result = future.result(timeout=tool.timeout_seconds)
                except FutureTimeout:
                    return ToolResult(
                        ok=False,
                        summary=f"Tool {name} timed out",
                        error=f"Tool {name} exceeded its {tool.timeout_seconds}s timeout.",
                    )
        except ToolError as exc:
            return ToolResult(
                ok=False,
                summary=f"Tool {name} failed",
                text="",
                error=exc.message,
                fatal=exc.fatal,
            )
        except Exception as exc:  # never let an exception escape into the agent loop
            return ToolResult(
                ok=False,
                summary=f"Tool {name} failed",
                text="",
                error=f"Unexpected error in tool {name}: {type(exc).__name__}",
            )

        if not isinstance(result, ToolResult):
            result = ToolResult(summary=f"Tool {name} returned", text=str(result)[:200])
        # Final safety bound on anything the model will see.
        result.text = truncate(result.text or "", self.max_output_chars)
        return result