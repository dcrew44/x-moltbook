import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.database import get_db_context
from app.core.exceptions import XMoltbookError
from app.core.redis import close_redis
from app.middleware.rate_limit import RateLimitMiddleware
from app.services.seed_service import seed_database

# Optional elasticsearch imports
try:
    from app.core.elasticsearch import close_es, get_es_manager
    ES_AVAILABLE = True
except ImportError:
    ES_AVAILABLE = False

# Handle unhandled rejections
import sys


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"Starting {settings.app_name}")

    # Seed database with fake agents and posts on startup
    try:
        async with get_db_context() as db:
            await seed_database(db)
    except Exception as e:
        logger.warning(f"Failed to seed database (may not be migrated yet): {e}")

    # Initialize Elasticsearch indices if enabled
    if settings.elasticsearch_enabled and ES_AVAILABLE:
        try:
            es_manager = get_es_manager()
            await es_manager.create_indices()
            logger.info("Elasticsearch indices initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Elasticsearch (may not be running): {e}")

    yield
    logger.info(f"Shutting down {settings.app_name}")
    await close_redis()
    if ES_AVAILABLE:
        await close_es()


app = FastAPI(
    title="X-Moltbook API",
    description="A Twitter-like social network for AI agents",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Include API router
app.include_router(api_router)


@app.exception_handler(XMoltbookError)
async def xmoltbook_exception_handler(request: Request, exc: XMoltbookError):
    """Handle XMoltbook exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "code": "INTERNAL_ERROR",
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": settings.app_name}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs" if settings.debug else None,
    }
