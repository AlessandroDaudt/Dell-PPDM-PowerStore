import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api import router
from app.config import get_settings
from app.database import Base, engine
from app.services.base_client import ExternalAPIError

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="SANFlow Dell API",
    description="Automação de LUNs PowerStore, zoning Brocade e proteção PPDM.",
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="strict",
    https_only=False,
    max_age=8 * 60 * 60,
)
app.include_router(router)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.exception_handler(ExternalAPIError)
async def external_api_exception_handler(_request: Request, exc: ExternalAPIError):
    return JSONResponse(
        status_code=502,
        content={
            "detail": str(exc),
            "system": exc.system,
            "upstream_status": exc.status_code,
        },
    )


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "version": __version__}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_dir / "index.html")
