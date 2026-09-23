"""Producer-side helpers that build well-formed event payloads and hand them
to the fire-and-forget Kafka client (app.core.kafka_client).

Every function here is synchronous and returns immediately -- it schedules
the actual network send as a background task via
kafka_client.publish_event_nowait, so calling these from the auction's
critical path adds no measurable latency (Section 9 of the spec: "Do NOT
perform expensive analytics synchronously inside the auction request").
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.kafka_client import publish_event_nowait
from app.events import topics


def _event_envelope(event_type: str, **fields) -> dict:
    return {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }


def publish_auction_completed(
    auction_id: str,
    winning_dsp: str | None,
    winning_bid: float | None,
    latency_ms: int,
    status: str,
) -> None:
    payload = _event_envelope(
        "AUCTION_COMPLETED" if status == "COMPLETED" else "AUCTION_NO_BID",
        auction_id=auction_id,
        winning_dsp=winning_dsp,
        winning_bid=winning_bid,
        latency_ms=latency_ms,
        status=status,
    )
    publish_event_nowait(topics.AUCTION_EVENTS, key=auction_id, payload=payload)


def publish_bid_event(auction_id: str, dsp_name: str, amount: float, status: str) -> None:
    payload = _event_envelope(
        "BID_RECEIVED", auction_id=auction_id, dsp_name=dsp_name, amount=amount, status=status
    )
    publish_event_nowait(topics.BID_EVENTS, key=auction_id, payload=payload)


def publish_impression_event(auction_id: str, campaign_id: str) -> None:
    payload = _event_envelope("IMPRESSION_RECORDED", auction_id=auction_id, campaign_id=campaign_id)
    publish_event_nowait(topics.IMPRESSION_EVENTS, key=campaign_id, payload=payload)


def publish_click_event(impression_id: str) -> None:
    payload = _event_envelope("CLICK_RECORDED", impression_id=impression_id)
    publish_event_nowait(topics.CLICK_EVENTS, key=impression_id, payload=payload)


def publish_campaign_event(campaign_id: str, event_type: str, **extra) -> None:
    payload = _event_envelope(event_type, campaign_id=campaign_id, **extra)
    publish_event_nowait(topics.CAMPAIGN_EVENTS, key=campaign_id, payload=payload)