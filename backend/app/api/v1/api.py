from fastapi import APIRouter

from app.api.v1.endpoints import receipts

# --- API v1 Router Aggregator ---
# Reference: LDD Section 1 (api.py - Router Aggregator)
#
# Collects all endpoint routers under the /api/v1 prefix.
# Add new routers here as they are implemented (pos, analytics).

api_router = APIRouter(prefix="/api/v1")

# Receipt Management endpoints
api_router.include_router(receipts.router)

# TODO (Prompt 6): POS endpoints
# from app.api.v1.endpoints import pos
# api_router.include_router(pos.router)

# TODO (Prompt 6): Analytics endpoints
# from app.api.v1.endpoints import analytics
# api_router.include_router(analytics.router)
