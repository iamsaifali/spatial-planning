import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.errors import INTERNAL_ERROR, VALIDATION_ERROR, AppError
from app.services.catalog import CatalogRepository, set_repository
from app.services.persistence.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("zory")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    static_dir = settings.resolve(settings.static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "products").mkdir(parents=True, exist_ok=True)

    repo = CatalogRepository.load(settings.resolve(settings.catalog_path), static_dir)
    set_repository(repo)
    logger.info("Catalog loaded: %d products", len(repo.all()))

    init_db(settings.resolve(settings.db_path))
    logger.info("SQLite ready at %s", settings.resolve(settings.db_path))
    logger.info("LLM enabled: %s (model=%s)", settings.llm_enabled, settings.openai_model)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.startswith("/static"):
            logger.info(
                "%s %s -> %d (%.0f ms) [%s]",
                request.method, request.url.path, response.status_code, elapsed_ms, request_id,
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        details = [
            {"loc": [str(p) for p in err.get("loc", [])], "message": err.get("msg", "")}
            for err in exc.errors()[:20]
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": VALIDATION_ERROR,
                    "message": "The request payload is invalid.",
                    "details": details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": INTERNAL_ERROR, "message": "Something went wrong on our side."}},
        )

    from app.routers import (
        assistant,
        checkout,
        config as config_router,
        designs,
        guide,
        health,
        placement,
        products,
        render,
        rooms,
        summary,
    )

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(config_router.router, prefix=api_prefix)
    app.include_router(rooms.router, prefix=api_prefix)
    app.include_router(guide.router, prefix=api_prefix)
    app.include_router(placement.router, prefix=api_prefix)
    app.include_router(products.router, prefix=api_prefix)
    app.include_router(summary.router, prefix=api_prefix)
    app.include_router(render.router, prefix=api_prefix)
    app.include_router(assistant.router, prefix=api_prefix)
    app.include_router(designs.router, prefix=api_prefix)
    app.include_router(checkout.router, prefix=api_prefix)

    settings_static = get_settings()
    app.mount(
        "/static",
        StaticFiles(directory=settings_static.resolve(settings_static.static_dir)),
        name="static",
    )
    return app


app = create_app()
