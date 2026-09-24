from fastapi import APIRouter

from app.api.v1 import analytics, auctions, auth, bids, campaigns, dsps

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(campaigns.router)
api_router.include_router(dsps.router)
api_router.include_router(auctions.router)
api_router.include_router(bids.router)
api_router.include_router(analytics.router)
