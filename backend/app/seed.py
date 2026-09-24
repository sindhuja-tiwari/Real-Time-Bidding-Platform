"""One-shot seed script for local/demo use.

Run inside the backend container after migrations:
    docker compose exec backend python -m app.seed

Creates:
- one advertiser with 5 campaigns (one per simulated DSP, matching Section 13's
  example base_bid/latency values so the numbers in the auction-detail page
  match the numbers in docs/performance.md)
- one publisher + ad_slot
- 5 DSP rows in Postgres, each pointing at the shared dsp-simulator container
- pushes each campaign's real UUID into the simulator's config so bids
  reference campaigns that actually exist
"""
import asyncio
import os

import httpx

from app.core.db import AsyncSessionLocal
from app.models.campaign import Campaign
from app.models.creative import Creative
from app.models.dsp import DSP
from app.models.publisher import AdSlot, Publisher
from app.models.user import Advertiser

DSP_SIMULATOR_URL = os.getenv("DSP_SIMULATOR_URL", "http://dsp-simulator:9000")

DSP_SEED = [
    {"name": "DSP-A", "base_bid": 2.5, "latency_ms": 20, "timeout_probability": 0.0},
    {"name": "DSP-B", "base_bid": 3.2, "latency_ms": 50, "timeout_probability": 0.02},
    {"name": "DSP-C", "base_bid": 4.1, "latency_ms": 150, "timeout_probability": 0.35},
    {"name": "DSP-D", "base_bid": 2.9, "latency_ms": 35, "timeout_probability": 0.01},
    {"name": "DSP-E", "base_bid": 1.8, "latency_ms": 60, "timeout_probability": 0.05},
]


async def seed() -> None:
    from datetime import datetime, timedelta, timezone

    async with AsyncSessionLocal() as db:
        advertiser = Advertiser(name="Demo Advertiser", budget=100000)
        db.add(advertiser)
        await db.flush()

        publisher = Publisher(name="Demo Publisher")
        db.add(publisher)
        await db.flush()

        ad_slot = AdSlot(publisher_id=publisher.id, placement="homepage-banner", width=300, height=250, floor_price=0.5)
        db.add(ad_slot)
        await db.flush()

        now = datetime.now(timezone.utc)
        campaign_ids = {}
        for spec in DSP_SEED:
            campaign = Campaign(
                advertiser_id=advertiser.id,
                name=f"Campaign for {spec['name']}",
                daily_budget=1000,
                remaining_budget=1000,
                bid_floor=0.1,
                target_countries=[],
                target_devices=[],
                status="ACTIVE",
                start_time=now - timedelta(days=1),
                end_time=now + timedelta(days=30),
            )
            db.add(campaign)
            await db.flush()

            creative = Creative(
                campaign_id=campaign.id,
                title=f"{spec['name']} creative",
                image_url=f"https://picsum.photos/seed/{spec['name']}/300/250",
                landing_url="https://example.com",
                status="ACTIVE",
            )
            db.add(creative)

            dsp = DSP(
                name=spec["name"],
                endpoint=f"{DSP_SIMULATOR_URL}/{spec['name'].lower()}",
                timeout_ms=100,
                status="ACTIVE",
            )
            db.add(dsp)

            campaign_ids[spec["name"]] = str(campaign.id)

        await db.commit()

    async with httpx.AsyncClient() as client:
        for spec in DSP_SEED:
            payload = {
                "campaign_id": campaign_ids[spec["name"]],
                "base_bid": spec["base_bid"],
                "latency_ms": spec["latency_ms"],
                "latency_jitter_ms": 10,
                "failure_probability": 0.02,
                "timeout_probability": spec["timeout_probability"],
                "quality_score": 0.8,
                "accepted_countries": ["*"],
                "accepted_devices": ["*"],
            }
            resp = await client.post(
                f"{DSP_SIMULATOR_URL}/admin/dsps/{spec['name'].lower()}", json=payload, timeout=10
            )
            resp.raise_for_status()

    print("Seed complete:")
    print(f"  ad_slot_id = {ad_slot.id}")
    for name, cid in campaign_ids.items():
        print(f"  {name} -> campaign_id={cid}")


if __name__ == "__main__":
    asyncio.run(seed())
