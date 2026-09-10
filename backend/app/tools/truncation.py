"""Bounded tool output helpers."""
from __future__ import annotations

_TRUNCATION_MARK = "\n…[output truncated]"


def truncate(text: str, max_chars: int, *, keep_head: bool = True) -> str:
    """Return ``text`` bounded to ``max_chars``.

    Truncation is applied both to large tool results and to the context
    inserted into the LLM conversation so memory stays bounded.
    """
    if max_chars <= 0:
        return _TRUNCATION_MARK.strip()
    if len(text) <= max_chars:
        return text
    limit = max(0, max_chars - len(_TRUNCATION_MARK))
    head = text[:limit]
    if not keep_head:
        return _TRUNCATION_MARK.strip() + text[-limit:]
    return head + _TRUNCATION_MARK


def truncate_lines(text: str, max_lines: int, max_chars: int) -> str:
    """Bound by both line count and total character count."""
    lines = text.splitlines()
    bounded_lines = lines[:max_lines]
    if len(lines) > max_lines:
        bounded_lines.append(_TRUNCATION_MARK.strip())
    return truncate("\n".join(bounded_lines), max_chars)