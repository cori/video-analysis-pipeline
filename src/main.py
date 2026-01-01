"""FastAPI application entry point for FPV Video Analyzer."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.api.routes import router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting FPV Video Analyzer v{settings.app_version}")
    logger.info(f"Ollama host: {settings.ollama_host}")
    logger.info(f"Ollama model: {settings.ollama_model}")
    logger.info(f"Crawler enabled: {settings.crawler_enabled}")

    # TODO: Initialize crawler if enabled
    if settings.crawler_enabled:
        logger.info(f"Crawler will scan: {settings.crawler_root}")
        logger.info(f"Crawler interval: {settings.crawler_interval}s")

    yield

    # Shutdown
    logger.info("Shutting down FPV Video Analyzer")


# Create FastAPI app
app = FastAPI(
    title="FPV Video Analyzer",
    description="Automated analysis of FPV drone footage using local LLMs",
    version=settings.app_version,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "FPV Video Analyzer",
        "version": settings.app_version,
        "status": "running",
        "endpoints": {
            "analyze": "POST /analyze",
            "status": "GET /status",
            "health": "GET /health",
            "metadata": "GET /video/{path}/metadata",
            "trigger_crawler": "POST /crawler/trigger",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
