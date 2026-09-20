from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
