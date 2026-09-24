"""Generic at-least-once consumer runner.

Used by each of the three consumers (analytics/audit/budget). Retry policy
(Section 15 of the spec):

  Attempt 1 -> immediately
  Attempt 2 -> 1s
  Attempt 3 -> 2s
  Attempt 4 -> 4s
  after EVENT_MAX_RETRIES -> publish to the dead-letter topic and move on

This is deliberately different from the auction's synchronous path, which
never retries (a retried auction call would blow the 100ms deadline).
Analytics/audit/budget-reconciliation processing has no such deadline, so
retrying with backoff to ride out a transient Postgres blip or a consumer
bug is the right trade-off there.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import KAFKA_CONSUMER_LAG
from app.events.topics import DEAD_LETTER

settings = get_settings()
logger = get_logger(__name__)

Handler = Callable[[dict], Awaitable[None]]


async def _send_to_dlq(producer: AIOKafkaProducer, original_topic: str, payload: dict, error: str) -> None:
    dlq_payload = {"original_topic": original_topic, "error": error, "payload": payload}
    try:
        await producer.send_and_wait(
            DEAD_LETTER, json.dumps(dlq_payload).encode("utf-8"), key=original_topic.encode("utf-8")
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("dlq_publish_failed", error=str(exc), original_topic=original_topic)


async def run_consumer(
    topic: str,
    group_id: str,
    handler: Handler,
    max_retries: int | None = None,
    base_backoff: float | None = None,
) -> None:
    max_retries = max_retries or settings.EVENT_MAX_RETRIES
    base_backoff = base_backoff or settings.EVENT_RETRY_BASE_SECONDS

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    dlq_producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)

    await consumer.start()
    await dlq_producer.start()
    logger.info("consumer_started", topic=topic, group_id=group_id)

    try:
        async for msg in consumer:
            payload = msg.value
            attempt = 0
            while True:
                try:
                    await handler(payload)
                    await consumer.commit()
                    break
                except Exception as exc:  # noqa: BLE001
                    attempt += 1
                    if attempt > max_retries:
                        logger.error(
                            "consumer_max_retries_exceeded",
                            topic=topic, group_id=group_id, error=str(exc),
                        )
                        await _send_to_dlq(dlq_producer, topic, payload, str(exc))
                        await consumer.commit()
                        break
                    backoff = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "consumer_retry", topic=topic, attempt=attempt,
                        backoff_seconds=backoff, error=str(exc),
                    )
                    await asyncio.sleep(backoff)

            # Best-effort lag reporting (end offset - current position).
            try:
                partitions = consumer.assignment()
                for tp in partitions:
                    end_offsets = await consumer.end_offsets([tp])
                    position = await consumer.position(tp)
                    lag = max(end_offsets[tp] - position, 0)
                    KAFKA_CONSUMER_LAG.labels(group=group_id, topic=topic).set(lag)
            except Exception:  # noqa: BLE001
                pass
    finally:
        await consumer.stop()
        await dlq_producer.stop()
