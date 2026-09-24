"""Audit consumer.

Writes every event verbatim to an append-only audit log (here: structured
logs, which in production would be shipped to a durable store like S3 or a
dedicated audit table). This consumer intentionally does no interpretation
of the event -- it's the system's source of truth for "what happened and
when" independent of whatever the analytics rollups compute.
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)


async def handle_audit_event(payload: dict) -> None:
    logger.info("audit_log", **payload)
