import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.creative import Creative
from app.models.publisher import AdSlot, Publisher
from app.models.user import User


class AdSlotRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, ad_slot_id: uuid.UUID) -> AdSlot | None:
        return await self.db.get(AdSlot, ad_slot_id)

    async def get_or_create_default(self, ad_slot_id: uuid.UUID, width: int, height: int) -> AdSlot:
        """Convenience for local/demo use: if the publisher's ad_slot isn't
        registered yet, create it under a default publisher rather than
        rejecting the auction request outright."""
        slot = await self.get(ad_slot_id)
        if slot:
            return slot
        result = await self.db.execute(select(Publisher).limit(1))
        publisher = result.scalar_one_or_none()
        if publisher is None:
            publisher = Publisher(name="default-publisher")
            self.db.add(publisher)
            await self.db.flush()
        slot = AdSlot(
            id=ad_slot_id, publisher_id=publisher.id, placement="default", width=width, height=height
        )
        self.db.add(slot)
        await self.db.commit()
        await self.db.refresh(slot)
        return slot


class CreativeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_for_campaign(self, campaign_id: uuid.UUID) -> Creative | None:
        stmt = select(Creative).where(
            Creative.campaign_id == campaign_id, Creative.status == "ACTIVE"
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user