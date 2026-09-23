import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dsp import DSP


class DSPRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, dsp_id: uuid.UUID) -> DSP | None:
        return await self.db.get(DSP, dsp_id)

    async def list_active(self) -> list[DSP]:
        result = await self.db.execute(select(DSP).where(DSP.status == "ACTIVE"))
        return list(result.scalars().all())

    async def list_all(self) -> list[DSP]:
        result = await self.db.execute(select(DSP))
        return list(result.scalars().all())

    async def create(self, dsp: DSP) -> DSP:
        self.db.add(dsp)
        await self.db.commit()
        await self.db.refresh(dsp)
        return dsp