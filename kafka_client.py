"""Kafka producer wrapper.

Design decisions (see docs/failure-handling.md for the full writeup):

1. Publishing is fire-and-forget from the auction's perspective: the auction
   request is never awaited on a Kafka round trip. `publish_event` schedules
   the send as a background asyncio task.
2. If Kafka is down, the auction still completes -- we log a warning and
   increment a metric instead of raising. Losing an analytics event is an
   acceptable trade-off for keeping the auction path's latency guarantee;
   losing the auction result itself is not (that's why the auction/bid rows
   are committed to Postgres *before* we attempt to publish).
3. Retries with exponential backoff are handled by `events/producer.py`
   which wraps this client for the cases where at-least-once delivery
   matters (e.g. budget consumer); the raw client here does not retry
   because retrying on the hot path would reintroduce the latency the
   fire-and-forget design is trying to avoid.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import KAFKA_PUBLISH_FAILURES, KAFKA_PUBLISH_TOTAL

settings = get_settings()
logger = get_logger(__name__)

_producer: AIOKafkaProducer | None = None
_lock = asyncio.Lock()


async def get_producer() -> AIOKafkaProducer | None:
    global _producer
    if not settings.KAFKA_ENABLED:
        return None
    if _producer is not None:
        return _producer
    async with _lock:
        if _producer is None:
            producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                enable_idempotence=True,  # dedupes producer-side retries at the broker
                acks="all",
            )
            try:
                await producer.start()
                _producer = producer
            except Exception as exc:  # noqa: BLE001
                logger.warning("kafka_producer_start_failed", error=str(exc))
                return None
    return _producer


async def stop_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def _do_publish(topic: str, key: str, payload: dict[str, Any]) -> None:
    producer = await get_producer()
    if producer is None:
        KAFKA_PUBLISH_FAILURES.labels(topic=topic).inc()
        logger.warning("kafka_publish_skipped_unavailable", topic=topic, key=key)
        return
    try:
        await producer.send_and_wait(topic, value=payload, key=key.encode("utf-8"))
        KAFKA_PUBLISH_TOTAL.labels(topic=topic).inc()
    except Exception as exc:  # noqa: BLE001
        KAFKA_PUBLISH_FAILURES.labels(topic=topic).inc()
        logger.warning("kafka_publish_failed", topic=topic, key=key, error=str(exc))


def publish_event_nowait(topic: str, key: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget publish -- never awaited by the auction critical path."""
    try:
        asyncio.get_running_loop().create_task(_do_publish(topic, key, payload))
    except RuntimeError:
        # No running loop (e.g. called from sync test code) -- best effort.
        logger.warning("kafka_publish_no_event_loop", topic=topic, key=key)