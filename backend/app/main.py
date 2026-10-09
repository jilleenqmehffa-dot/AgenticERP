from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.reservation_recommendations import router as reservation_review_router
from app.api.inventory_adjustments import router as inventory_adjustment_router
from app.core.config import get_settings
from app.db.session import create_session_factory, get_db_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine, app.state.session_factory = create_session_factory(
        get_settings().database_url
    )
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="AgenticERP", lifespan=lifespan)
app.include_router(reservation_review_router)
app.include_router(inventory_adjustment_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
