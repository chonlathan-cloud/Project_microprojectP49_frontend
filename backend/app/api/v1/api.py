from fastapi import APIRouter

from app.api.v1.endpoints import receipts, analytics

# --- API v1 Router Aggregator ---
# Reference: LDD Section 1 (api.py - Router Aggregator)
#
# Collects all endpoint routers under the /api/v1 prefix.

api_router = APIRouter(prefix="/api/v1")

# Receipt Management endpoints
api_router.include_router(receipts.router)

# Analytics endpoints
api_router.include_router(analytics.router)

# TODO (Prompt 7): POS endpoints
# from app.api.v1.endpoints import pos
# api_router.include_router(pos.router)
