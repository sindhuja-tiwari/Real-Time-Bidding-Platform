from __future__ import annotations

import json
import uuid

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.redis_client import safe_delete, safe_get, safe_set
from app.models.dsp import DSP
from app.repositories.dsp_repository import DSPRepository

settings = get_settings()


class DSPService:
    def __init__(self, db: AsyncSession, redis_client: redis.Redis):
        self.db = db
        self.redis = redis_client
        self.repo = DSPRepository(db)

    async def create(self, **fields) -> DSP:
        dsp = DSP(**fields)
        return await self.repo.create(dsp)

    async def get(self, dsp_id: uuid.UUID) -> DSP:
        dsp = await self.repo.get(dsp_id)
        if dsp is None:
            raise NotFoundError(f"DSP {dsp_id} not found")
        return dsp

    async def list_all(self) -> list[DSP]:
        return await self.repo.list_all()

    async def list_active_cached(self) -> list[DSP]:
        """Active DSPs are looked up on every auction -- cache-aside with a
        short TTL so an admin disabling a DSP takes effect within seconds."""
        cache_key = "dsp:active"
        raw = await safe_get(self.redis, cache_key)
        if raw:
            data = json.loads(raw)
            return [DSP(**d) for d in data]

        dsps = await self.repo.list_active()
        serializable = [
            {"id": d.id, "name": d.name, "endpoint": d.endpoint, "timeout_ms": d.timeout_ms, "status": d.status}
            for d in dsps
        ]
        await safe_set(self.redis, cache_key, json.dumps(serializable, default=str), settings.REDIS_CACHE_TTL_SECONDS)
        return dsps

    async def invalidate_cache(self) -> None:
        await safe_delete(self.redis, "dsp:active")
