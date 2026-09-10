"""Logging configuration for GitPilot.

Never log secrets: the log formatter redacts values that look like tokens
or API keys, and application code must not log authorization headers,
GitHub tokens, or LLM API keys.
"""
from __future__ import annotations

import logging
import re
import sys

# Fields that may carry secrets and must never reach logs.
_SECRET_FIELD_PATTERNS = [
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
]


def _redact(msg: object) -> str:
    text = str(msg)
    # Redact common token formats: gh[pousr]_*, sk-*, and bare 40-char hex.
    text = re.sub(r"gh[pousr]_[A-Za-z0-9]+", "[REDACTED]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    text = re.sub(r"\b[0-9a-fA-F]{40}\b", "[REDACTED]", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts token-like values in log records."""

    def format(self, record: logging.LogRecord) -> str:
        # Redact the message body and the exception traceback text.
        record.msg = _redact(record.msg)
        if record.exc_info and record.exc_text is None:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _redact(record.exc_text)
        return super().format(record)


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("gitpilot")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s [%(analysis_id)s] %(message)s"
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(analysis_id: str | None = None) -> logging.Logger:
    """Return the application logger. When an analysis is active, pass its
    id via the `extra` mechanism so every record is correlated."""
    logger = logging.getLogger("gitpilot")
    if analysis_id is not None:
        return logging.LoggerAdapter(
            logger, {"analysis_id": analysis_id or "-"}
        )
    return logger