"""DSP Simulator (Section 13 of the spec).

Simulates N demand-side platforms behind one FastAPI process, each reachable
at /{dsp_name}/bid. Each DSP has independently configurable base_bid,
latency, jitter, failure_probability, timeout_probability, and quality_score,
mutable at runtime via the /admin endpoints -- this is what lets the load
tests and the frontend "system" page demonstrate what happens when a DSP
gets slow or starts failing, without redeploying anything.

DSP-C is seeded to frequently miss the platform's default 100ms auction
deadline (latency_ms=150) specifically to make that failure mode visible in
a demo (Section 13: "This should allow demonstration of why low latency
matters").
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI(title="DSP Simulator")


class DSPConfig(BaseModel):
    campaign_id: str
    base_bid: float
    latency_ms: int
    latency_jitter_ms: int = 10
    failure_probability: float = Field(ge=0, le=1, default=0.0)
    timeout_probability: float = Field(ge=0, le=1, default=0.0)
    quality_score: float = Field(ge=0, le=1, default=0.8)
    accepted_countries: list[str] = Field(default_factory=lambda: ["*"])
    accepted_devices: list[str] = Field(default_factory=lambda: ["*"])


class BidRequestIn(BaseModel):
    request_id: str
    ad_slot_id: str
    country: str
    device: str


# In-memory config store. Seeded with the exact example values from the spec.
CONFIGS: dict[str, DSPConfig] = {
    "dsp-a": DSPConfig(campaign_id="", base_bid=2.5, latency_ms=20, failure_probability=0.01, timeout_probability=0.0, quality_score=0.9),
    "dsp-b": DSPConfig(campaign_id="", base_bid=3.2, latency_ms=50, failure_probability=0.02, timeout_probability=0.02, quality_score=0.85),
    "dsp-c": DSPConfig(campaign_id="", base_bid=4.1, latency_ms=150, failure_probability=0.02, timeout_probability=0.35, quality_score=0.7),
    "dsp-d": DSPConfig(campaign_id="", base_bid=2.9, latency_ms=35, failure_probability=0.01, timeout_probability=0.01, quality_score=0.8),
    "dsp-e": DSPConfig(campaign_id="", base_bid=1.8, latency_ms=60, failure_probability=0.05, timeout_probability=0.05, quality_score=0.75),
}


@app.get("/health")
async def health():
    return {"status": "ok", "dsps": list(CONFIGS.keys())}


@app.get("/admin/dsps")
async def list_configs():
    return CONFIGS


@app.post("/admin/dsps/{name}")
async def set_config(name: str, config: DSPConfig):
    """Admin interface (Section 13) to change a DSP's behavior at runtime,
    e.g. to demonstrate failure modes in the frontend's /system page."""
    CONFIGS[name] = config
    return config


@app.post("/{name}/bid")
async def bid(name: str, request: BidRequestIn, response: Response):
    config = CONFIGS.get(name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown DSP simulator '{name}'")

    if config.accepted_countries != ["*"] and request.country not in config.accepted_countries:
        response.status_code = 204
        return

    if config.accepted_devices != ["*"] and request.device not in config.accepted_devices:
        response.status_code = 204
        return

    # Simulate a hung/very slow DSP -- the caller's own timeout is what
    # actually protects the auction; we don't self-limit here on purpose.
    if random.random() < config.timeout_probability:
        await asyncio.sleep(2.0)  # far beyond any sane per-DSP timeout
        response.status_code = 204
        return

    jitter = random.uniform(-config.latency_jitter_ms, config.latency_jitter_ms)
    await asyncio.sleep(max(0, config.latency_ms + jitter) / 1000)

    if random.random() < config.failure_probability:
        raise HTTPException(status_code=500, detail="Simulated DSP failure")

    if not config.campaign_id:
        response.status_code = 204
        return

    bid_amount = round(max(0, config.base_bid + random.uniform(-0.3, 0.3)), 4)
    return {
        "campaign_id": config.campaign_id,
        "amount": bid_amount,
        "quality_score": config.quality_score,
    }
