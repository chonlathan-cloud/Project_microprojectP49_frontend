from fastapi import FastAPI

app = FastAPI(
    title="SPA 49 Notification Worker",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, object]:
    return {"status": "ready", "dependencies": {"templates": "ready"}}
