from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.database import engine, Base
from app.routers import vehicles, schedules, entries, dashboard
import logging

logging.basicConfig(
    level=logging.DEBUG,  # swap to INFO in production
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (idempotent — use Alembic in prod for migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    root_path="/api",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vehicles.router, prefix="/v1")
app.include_router(schedules.router, prefix="/v1")
app.include_router(entries.router,   prefix="/v1")
app.include_router(dashboard.router, prefix="/v1")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": settings.app_name}
