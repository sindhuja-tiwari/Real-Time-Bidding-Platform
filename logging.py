"""Structured JSON logging.

Every log line is a JSON object. request_id / auction_id are threaded through
via contextvars so that a single auction's logs can be grepped end to end
without passing loggers down every function call.
"""
from __future__ import annotations

import contextvars
import logging
import sys
import time
from typing import Any

import structlog

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
auction_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "auction_id", default=None
)

_SENSITIVE_KEYS = {"password", "password_hash", "jwt_secret", "authorization", "token"}


def _redact_sensitive(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def _inject_correlation_ids(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    rid = request_id_var.get()
    aid = auction_id_var.get()
    if rid:
        event_dict.setdefault("request_id", rid)
    if aid:
        event_dict.setdefault("auction_id", aid)
    return event_dict


def configure_logging(env: str = "local") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if env != "local" else logging.DEBUG,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_correlation_ids,
            _redact_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class Timer:
    """Small helper for measuring elapsed milliseconds."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000