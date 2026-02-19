from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.config import settings
from app.services import knowledge_base

# --- FastAPI Application Entry Point ---
# Reference: LDD Section 1 (main.py), TDD Section 4.2 (CORS)

app = FastAPI(
    title="The 491 - Smart P&L Analysis API",
    description="Backend API for receipt processing, expense categorization, and P&L analytics.",
    version="1.0.0",
)

# --- CORS Middleware ---
# Reference: TDD Section 4.2 (Security - CORS)
# Allow all origins for local development. Restrict in production.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Include API Routers ---

app.include_router(api_router)


# --- Startup hooks ---

@app.on_event("startup")
async def startup_event():
    """Warm up optional services for better first-request latency."""
    if settings.KNOWLEDGE_BASE_AUTO_INIT:
        knowledge_base.initialize_knowledge_base()


# --- Health Check ---

@app.get("/", tags=["Health"])
async def health_check():
    """Root endpoint for health check / Cloud Run readiness probe."""
    return {
        "status": "ok",
        "service": "the491-api",
        "version": "1.0.0",
    }
