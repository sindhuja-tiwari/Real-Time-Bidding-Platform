from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign


class CampaignRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, campaign_id: uuid.UUID) -> Campaign | None:
        return await self.db.get(Campaign, campaign_id)

    async def list(self, advertiser_id: uuid.UUID | None = None) -> list[Campaign]:
        stmt = select(Campaign)
        if advertiser_id:
            stmt = stmt.where(Campaign.advertiser_id == advertiser_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, campaign: Campaign) -> Campaign:
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def update(self, campaign: Campaign, **fields) -> Campaign:
        for key, value in fields.items():
            if value is not None:
                setattr(campaign, key, value)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def eligible_for_slot(self, country: str, device: str) -> list[Campaign]:
        """Phase 1 fallback for the cache-aside lookup described in
        docs/architecture.md Section 6. This is a straight Postgres query;
        Phase 3 puts a Redis cache-aside layer in front of it so the auction
        path doesn't hit Postgres on every request.
        """
        now = datetime.now(timezone.utc)
        stmt = select(Campaign).where(
            Campaign.status == "ACTIVE",
            Campaign.start_time <= now,
            Campaign.end_time >= now,
            Campaign.remaining_budget > 0,
        )
        result = await self.db.execute(stmt)
        campaigns = list(result.scalars().all())
        # Targeting filter done in Python: empty target list == "no restriction"
        return [
            c
            for c in campaigns
            if (not c.target_countries or country in c.target_countries)
            and (not c.target_devices or device in c.target_devices)
        ]

    async def reserve_budget(self, campaign_id: uuid.UUID, amount: float) -> bool:
        """Atomic budget reservation (docs/database.md Section 4).

        SELECT ... FOR UPDATE locks the campaign row so concurrent auctions
        targeting the same campaign serialize on this statement rather than
        racing on a read-then-write of remaining_budget. The UPDATE's WHERE
        clause re-checks the balance under the lock: if another transaction
        already spent the budget, zero rows are updated and we return False
        (the caller treats this as BUDGET_EXCEEDED, not an error).
        """
        locked = await self.db.execute(
            select(Campaign.remaining_budget).where(Campaign.id == campaign_id).with_for_update()
        )
        remaining = locked.scalar_one_or_none()
        if remaining is None or remaining < amount:
            await self.db.commit()
            return False

        result = await self.db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id, Campaign.remaining_budget >= amount)
            .values(remaining_budget=Campaign.remaining_budget - amount)
        )
        await self.db.commit()
        return result.rowcount == 1
