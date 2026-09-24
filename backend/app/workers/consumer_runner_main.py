"""Entrypoint for the `worker` container in docker-compose.

Runs the three consumers (analytics, audit, budget) as concurrent asyncio
tasks inside a single process. They're logically separate consumer groups
(each gets its own copy of every message), which is exactly why Kafka's
pub/sub model was chosen over a plain queue -- see docs/architecture.md.
"""
from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.events import topics
from app.events.consumer_runner import run_consumer
from app.events.consumers.analytics_consumer import handle_analytics_event
from app.events.consumers.audit_consumer import handle_audit_event
from app.events.consumers.budget_consumer import handle_budget_event

settings = get_settings()


async def main() -> None:
    configure_logging(settings.ENV)
    logger = get_logger(__name__)
    logger.info("worker_starting")

    await asyncio.gather(
        run_consumer(topics.AUCTION_EVENTS, settings.KAFKA_CONSUMER_GROUP_ANALYTICS, handle_analytics_event),
        run_consumer(topics.AUCTION_EVENTS, settings.KAFKA_CONSUMER_GROUP_AUDIT, handle_audit_event),
        run_consumer(topics.AUCTION_EVENTS, settings.KAFKA_CONSUMER_GROUP_BUDGET, handle_budget_event),
    )


if __name__ == "__main__":
    asyncio.run(main())
