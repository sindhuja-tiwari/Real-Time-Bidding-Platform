"""Campaign domain service.

Owns two different access patterns deliberately kept separate:

1. CRUD (create/update/list) -- always goes straight to Postgres, the
   system of record, and invalidates the Redis cache on any write.
2. `get_cached(id)` / `list_eligible_cached(...)` -- the auction-time
   cache-aside read path (Section 8 of the spec): Redis first, Postgres on
   miss, repopulate Redis on the way back out. This is what keeps the
   auction path off Postgres for the common case.
"""
from __future__ import annotations

import json
import uuid

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.metrics import CACHE_HIT_TOTAL, CACHE_MISS_TOTAL
from app.core.redis_client import safe_delete, safe_get, safe_set
from app.models.campaign import Campaign
from app.repositories.campaign_repository import CampaignRepository
from app.services.bidding.types import CampaignSnapshot

settings = get_settings()
logger = get_logger(__name__)


def _cache_key(campaign_id: uuid.UUID) -> str:
    return f"campaign:{campaign_id}"


def _to_snapshot(c: Campaign) -> CampaignSnapshot:
    return CampaignSnapshot(
        id=c.id,
        status=c.status,
        remaining_budget=float(c.remaining_budget),
        bid_floor=float(c.bid_floor),
        target_countries=list(c.target_countries or []),
        target_devices=list(c.target_devices or []),
    )


def _serialize(c: Campaign) -> str:
    return json.dumps(
        {
            "id": str(c.id),
            "status": c.status,
            "remaining_budget": float(c.remaining_budget),
            "bid_floor": float(c.bid_floor),
            "target_countries": list(c.target_countries or []),
            "target_devices": list(c.target_devices or []),
        }
    )


class CampaignService:
    def __init__(self, db: AsyncSession, redis_client: redis.Redis):
        self.db = db
        self.redis = redis_client
        self.repo = CampaignRepository(db)

    # ---------------- CRUD (system of record) ----------------

    async def create(self, **fields) -> Campaign:
        campaign = Campaign(remaining_budget=fields["daily_budget"], **fields)
        return await self.repo.create(campaign)

    async def get(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.repo.get(campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {campaign_id} not found")
        return campaign

    async def list(self, advertiser_id: uuid.UUID | None = None) -> list[Campaign]:
        return await self.repo.list(advertiser_id)

    async def update(self, campaign_id: uuid.UUID, **fields) -> Campaign:
        campaign = await self.get(campaign_id)
        updated = await self.repo.update(campaign, **fields)
        await self.invalidate_cache(campaign_id)  # Section 8: invalidate on config change
        return updated

    async def invalidate_cache(self, campaign_id: uuid.UUID) -> None:
        await safe_delete(self.redis, _cache_key(campaign_id))

    # ---------------- Cache-aside read path (auction-time) ----------------

    async def get_cached_snapshot(self, campaign_id: uuid.UUID) -> CampaignSnapshot | None:
        raw = await safe_get(self.redis, _cache_key(campaign_id))
        if raw:
            CACHE_HIT_TOTAL.labels(resource="campaign").inc()
            data = json.loads(raw)
            return CampaignSnapshot(
                id=uuid.UUID(data["id"]),
                status=data["status"],
                remaining_budget=data["remaining_budget"],
                bid_floor=data["bid_floor"],
                target_countries=data["target_countries"],
                target_devices=data["target_devices"],
            )

        CACHE_MISS_TOTAL.labels(resource="campaign").inc()
        campaign = await self.repo.get(campaign_id)
        if campaign is None:
            return None
        await safe_set(self.redis, _cache_key(campaign_id), _serialize(campaign), settings.REDIS_CACHE_TTL_SECONDS)
        return _to_snapshot(campaign)

    async def list_eligible(self, country: str, device: str) -> list[Campaign]:
        """Eligibility (which campaigns *could* bid) is a small, frequently
        changing set-membership query -- left on Postgres rather than cached
        as a list, since caching "the whole eligible set" invalidates on
        every campaign status flip anywhere in the system. Individual
        campaign snapshots (targeting/budget/status) ARE cached via
        get_cached_snapshot, which is what the hot path actually calls
        once per candidate."""
        return await self.repo.eligible_for_slot(country, device)

    async def reserve_budget(self, campaign_id: uuid.UUID, amount: float) -> bool:
        ok = await self.repo.reserve_budget(campaign_id, amount)
        if ok:
            await self.invalidate_cache(campaign_id)
        return ok
