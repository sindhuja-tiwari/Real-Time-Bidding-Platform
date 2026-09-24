from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis_dep, require_role
from app.core.db import get_db
from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate
from app.services.campaign.service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    redis_client=Depends(get_redis_dep),
    _user=Depends(require_role("ADMIN", "ADVERTISER")),
):
    service = CampaignService(db, redis_client)
    campaign = await service.create(**body.model_dump())
    return CampaignResponse.model_validate(campaign)


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    advertiser_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    redis_client=Depends(get_redis_dep),
):
    service = CampaignService(db, redis_client)
    campaigns = await service.list(advertiser_id)
    return [CampaignResponse.model_validate(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db), redis_client=Depends(get_redis_dep)
):
    service = CampaignService(db, redis_client)
    campaign = await service.get(campaign_id)
    return CampaignResponse.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    redis_client=Depends(get_redis_dep),
    _user=Depends(require_role("ADMIN", "ADVERTISER")),
):
    service = CampaignService(db, redis_client)
    campaign = await service.update(campaign_id, **body.model_dump(exclude_unset=True))
    return CampaignResponse.model_validate(campaign)
