"""Agent orchestrator — the tool-calling loop.

The agent decides which tools to call based on the issue and accumulated
evidence; nothing here hard-codes the investigation sequence. The loop is
bounded by maximum steps, an execution timeout, and bounded tool output.

On write-tool calls the orchestrator never executes: it records a pending
approval and returns the proposal as the tool result so the model can
continue. The actual write happens later, only via the approval endpoint.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent.context import AgentContext
from app.agent.prompt import (
    SYSTEM_PROMPT,
    build_correction_prompt,
    build_task_prompt,
)
from app.core.errors import (
    AgentError,
    AgentStepLimitError,
    AgentTimeoutError,
    LLMError,
    StructuredOutputError,
    ValidationError,
)
from app.core.validation import validate_issue_number, validate_repository
from app.models.resolution import ResolutionReport
from app.services.llm.base import LLMMessage, LLMProvider, ToolCall
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry
from app.tools.truncation import truncate

logger = logging.getLogger("gitpilot")

# Event types persisted by the service
EVENT_ANALYSIS_STARTED = "analysis_started"
EVENT_TOOL_STARTED = "tool_started"
EVENT_TOOL_COMPLETED = "tool_completed"
EVENT_TOOL_FAILED = "tool_failed"
EVENT_STATUS = "status"
EVENT_APPROVAL_PROPOSED = "approval_proposed"

EventSink = Callable[[str, str, str, str | None], None]
ApprovalSink = Callable[[str, dict, str], str]

_DUPLICATE_GUIDANCE = (
    "This exact {name} call was already executed earlier in this investigation; "
    "its full result is already in the conversation above and was NOT fetched "
    "again. Do not repeat the call. Instead, use the existing evidence to "
    "continue reasoning, or pick a DIFFERENT tool or different arguments if "
    "you genuinely need more information. When the evidence is sufficient, "
    "produce the final structured resolution report."
)


def _tool_call_signature(name: str, arguments: dict[str, Any]) -> str:
    """Stable signature for a tool invocation: tool name + normalized args.

    Keys are sorted and encoded canonically, so ``{"a": 1, "b": 2}`` and
    ``{"b": 2, "a": 1}`` are the same call, while any change in a value
    produces a different signature (legitimate re-use of a tool with
    different arguments is never blocked).
    """
    try:
        normalized = json.dumps(
            arguments, sort_keys=True, separators=(",", ":"), default=str
        )
    except (TypeError, ValueError):
        normalized = repr(sorted(arguments.items(), key=lambda kv: str(kv[0])))
    return f"{name}:{normalized}"


@dataclass
class AgentOutcome:
    completed: bool = False
    report: ResolutionReport | None = None
    error_message: str | None = None
    error_code: str | None = None
    limit_kind: str | None = None  # "steps" | "timeout"
    approvals_created: list[dict[str, Any]] = field(default_factory=list)


class AgentOrchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        *,
        max_steps: int = 20,
        timeout_seconds: int = 300,
        structured_output_retries: int = 2,
        event_sink: EventSink | None = None,
        approval_sink: ApprovalSink | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.structured_output_retries = structured_output_retries
        self._event_sink = event_sink
        self._approval_sink = approval_sink
        self.approvals_created: list[dict[str, Any]] = []

    # ---------------- public ----------------
    def run(self, repository: str, issue_number: int) -> AgentOutcome:
        try:
            validate_repository(repository)
            number = validate_issue_number(issue_number)
        except ValidationError as exc:
            return AgentOutcome(
                completed=False,
                error_message=exc.message,
                error_code=exc.code,
            )

        ctx = AgentContext(
            repository=repository,
            issue_number=number,
            max_steps=self.max_steps,
            timeout_seconds=self.timeout_seconds,
        )
        self._emit(EVENT_ANALYSIS_STARTED, "info", f"Starting analysis of {repository} issue #{number}")

        ctx.messages.append(LLMMessage(role="system", content=SYSTEM_PROMPT))
        ctx.messages.append(
            LLMMessage(role="user", content=build_task_prompt(repository, number))
        )
        # Signatures of read-tool calls already executed in THIS run. Used to
        # short-circuit exact duplicate requests from the model so a looping
        # agent cannot burn its whole step budget re-fetching the same file.
        executed_calls: set[str] = set()

        while True:
            if ctx.timed_out:
                return self._fail(
                    ctx,
                    AgentTimeoutError(
                        f"Agent execution exceeded the {self.timeout_seconds}s timeout."
                    ),
                    limit_kind="timeout",
                )
            if ctx.step_limit_reached:
                return self._fail(
                    ctx,
                    AgentStepLimitError(
                        f"Agent reached the maximum of {self.max_steps} tool calls."
                    ),
                    limit_kind="steps",
                )

            try:
                response = self.provider.complete(
                    ctx.messages,
                    self.registry.specs(),
                    response_format={"type": "json_object"},
                )
            except LLMError as exc:
                # Provider/configuration/network failures end the run cleanly
                # instead of crashing the background worker.
                return self._fail(ctx, exc)
            except Exception as exc:  # noqa: BLE001 — never escape the loop
                return self._fail(
                    ctx,
                    LLMError(f"LLM provider failed unexpectedly: {type(exc).__name__}"),
                )

            # Optional concise, safe status line from the model. Raw JSON
            # payloads (final structured answers) are never surfaced as status.
            if response.content:
                stripped = response.content.strip()
                if not stripped.startswith(("{", "[", "```")):
                    status = truncate(stripped, 200)
                    self._emit(EVENT_STATUS, "info", status)

            if not response.wants_tool_call:
                try:
                    outcome = self._handle_final_answer(ctx, response.content or "")
                except StructuredOutputError as exc:
                    return self._fail(ctx, exc)
                if outcome is not None:
                    return outcome
                continue  # a correction round was scheduled

            self._handle_tool_calls(ctx, response.tool_calls, executed_calls)
            if ctx.fatal_error is not None:
                return self._fail(ctx, ctx.fatal_error)

        # unreachable
        return self._fail(ctx, AgentError("Agent loop ended unexpectedly."))

    # ---------------- tool handling ----------------
    def _handle_tool_calls(
        self, ctx: AgentContext, tool_calls: list[ToolCall], executed_calls: set[str]
    ) -> None:
        # Append the assistant message once with all requested calls, then
        # append one bounded tool-result message per call.
        ctx.messages.append(
            LLMMessage(
                role="assistant",
                content=None,
                tool_calls=tool_calls,
            )
        )
        for tc in tool_calls:
            if ctx.step_limit_reached:
                break
            ctx.steps += 1
            result = self._execute_tool(ctx, tc, executed_calls)
            if result is None:
                continue
            ctx.messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=tc.id,
                    content=result.text or (result.error or ""),
                )
            )

    def _execute_tool(
        self, ctx: AgentContext, tc: ToolCall, executed_calls: set[str]
    ) -> ToolResult | None:
        tool = self.registry.get(tc.name)

        if tool is None:
            self._emit(
                EVENT_TOOL_FAILED,
                "failed",
                f"Unknown tool {tc.name}",
                tool_name=tc.name,
            )
            return ToolResult(ok=False, error=f"Unknown tool: {tc.name}")

        if tool.is_write:
            # NEVER execute. Record a pending approval instead. The approval
            # sink persists the record AND the approval_proposed timeline event.
            rationale = f"Agent proposed {tc.name} during investigation of issue #{ctx.issue_number}."
            try:
                approval_id = self._approval_sink(tc.name, tc.arguments, rationale)
            except Exception:
                approval_id = None
            self.approvals_created.append(
                {"action_type": tc.name, "payload": tc.arguments, "approval_id": approval_id}
            )
            return ToolResult(
                summary=f"{tc.name} proposed for approval",
                text=(
                    f"The {tc.name} action was NOT executed. It is pending user "
                    f"approval. Continue investigating or produce the final report."
                ),
                pending_approval=True,
            )

        # Duplicate guard (read tools only): skip an exact repeat of a call
        # that already executed in this run and tell the model to use the
        # existing evidence instead. Write tools never reach this path — the
        # approval branch above always runs for them, unchanged.
        signature = _tool_call_signature(tc.name, tc.arguments)
        if signature in executed_calls:
            self._emit(
                EVENT_STATUS,
                "duplicate",
                f"Skipped duplicate {tc.name} call (already executed)",
                tool_name=tc.name,
            )
            return ToolResult(
                summary=f"Duplicate {tc.name} call skipped",
                text=_DUPLICATE_GUIDANCE.format(name=tc.name),
            )
        executed_calls.add(signature)

        self._emit(
            EVENT_TOOL_STARTED,
            "started",
            f"Calling {tc.name}",
            tool_name=tc.name,
        )
        result = self.registry.execute(tc.name, tc.arguments)
        if result.ok:
            self._emit(
                EVENT_TOOL_COMPLETED,
                "completed",
                result.summary,
                tool_name=tc.name,
            )
        else:
            self._emit(
                EVENT_TOOL_FAILED,
                "failed",
                result.error or result.summary,
                tool_name=tc.name,
            )
            # Failure strategy: a missing/failed initial issue retrieval is
            # fatal; non-critical search failures are recorded and the agent
            # may continue.
            if tc.name == "get_issue":
                ctx.fatal_error = AgentError(
                    f"Unable to retrieve issue context ({tc.name} failed): "
                    f"{result.error}"
                )
        return result

    # ---------------- final answer ----------------
    def _handle_final_answer(
        self, ctx: AgentContext, content: str
    ) -> AgentOutcome | None:
        report = self._parse_report(content)
        if report is not None:
            # The analysis service records the final report_generated event
            # after the report has been validated and persisted.
            return AgentOutcome(
                completed=True, report=report, approvals_created=self.approvals_created
            )

        retries_left = self.structured_output_retries - ctx.output_retries
        if retries_left > 0:
            ctx.output_retries += 1
            schema = ResolutionReport.model_json_schema()
            ctx.messages.append(
                LLMMessage(
                    role="user",
                    content=build_correction_prompt(schema),
                )
            )
            self._emit(
                EVENT_STATUS,
                "retry",
                f"Structured output validation failed; requesting corrected JSON "
                f"({ctx.output_retries}/{self.structured_output_retries})",
            )
            return None  # continue the loop

        raise StructuredOutputError(
            "The model produced invalid structured output after "
            f"{self.structured_output_retries} retries."
        )

    @staticmethod
    def _parse_report(content: str) -> ResolutionReport | None:
        text = content.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return ResolutionReport.model_validate(data)
        except Exception:
            return None

    # ---------------- helpers ----------------
    def _fail(self, ctx: AgentContext, error: Exception, limit_kind: str | None = None) -> AgentOutcome:
        # Terminal failure events (analysis_failed / limit_reached) are recorded
        # once, by the analysis service, so the timeline has no duplicates.
        message = str(error)
        code = getattr(error, "code", "agent_error")
        return AgentOutcome(
            completed=False,
            error_message=message,
            error_code=code,
            limit_kind=limit_kind,
            approvals_created=self.approvals_created,
        )

    def _emit(self, event_type: str, status: str, summary: str, tool_name: str | None = None) -> None:
        if self._event_sink is not None:
            try:
                self._event_sink(event_type, status, summary, tool_name)
            except Exception:
                logger.exception("Failed to record execution event")