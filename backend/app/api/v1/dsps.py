from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis_dep, require_role
from app.core.db import get_db
from app.schemas.dsp import DSPCreate, DSPResponse
from app.services.dsp.service import DSPService

router = APIRouter(prefix="/dsps", tags=["dsps"])


@router.post("", response_model=DSPResponse, status_code=201)
async def create_dsp(
    body: DSPCreate,
    db: AsyncSession = Depends(get_db),
    redis_client=Depends(get_redis_dep),
    _user=Depends(require_role("ADMIN")),
):
    service = DSPService(db, redis_client)
    dsp = await service.create(**body.model_dump())
    await service.invalidate_cache()
    return DSPResponse.model_validate(dsp)


@router.get("", response_model=list[DSPResponse])
async def list_dsps(db: AsyncSession = Depends(get_db), redis_client=Depends(get_redis_dep)):
    service = DSPService(db, redis_client)
    dsps = await service.list_all()
    return [DSPResponse.model_validate(d) for d in dsps]


@router.get("/{dsp_id}", response_model=DSPResponse)
async def get_dsp(dsp_id: uuid.UUID, db: AsyncSession = Depends(get_db), redis_client=Depends(get_redis_dep)):
    service = DSPService(db, redis_client)
    dsp = await service.get(dsp_id)
    return DSPResponse.model_validate(dsp)
