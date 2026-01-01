"""FastAPI routes for video analysis API."""

import json
import logging
import os
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from src.api.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    StatusResponse,
    HealthResponse,
    CrawlerStatus,
    CrawlerTriggerResponse,
)
from src.config import settings
from src.analysis.pipeline import AnalysisPipeline

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Global pipeline instance
pipeline: AnalysisPipeline = None


def get_pipeline() -> AnalysisPipeline:
    """Get or create pipeline instance."""
    global pipeline
    if pipeline is None:
        pipeline = AnalysisPipeline()
    return pipeline


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_video(request: AnalyzeRequest):
    """
    Analyze a single video file and generate metadata sidecar.

    Args:
        request: Analysis request with video path and options

    Returns:
        Analysis results

    Raises:
        HTTPException: Various error conditions
    """
    logger.info(f"Received analysis request for: {request.path}")

    # Validate file exists
    if not os.path.exists(request.path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File not found: {request.path}"
        )

    # Check if it's a video file
    video_extensions = {".mp4", ".mov", ".avi", ".mkv"}
    if not any(request.path.lower().endswith(ext) for ext in video_extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not a video file: {request.path}"
        )

    # Check if sidecar exists
    sidecar_path = request.path + ".meta.json"
    if os.path.exists(sidecar_path) and not request.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sidecar already exists: {sidecar_path}. Use force=true to re-analyze."
        )

    # Check Ollama availability
    pipe = get_pipeline()
    ollama_available = await pipe.check_ollama_health()
    if not ollama_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama service is unavailable"
        )

    # Perform analysis
    try:
        metadata = await pipe.analyze_video(request.path, force=request.force)

        return AnalyzeResponse(
            status="complete",
            path=request.path,
            sidecar=sidecar_path,
            duration_seconds=metadata.source.duration_seconds,
            tags=metadata.tags,
            highlights_count=len(metadata.highlights),
            static_segments_count=len(metadata.static_segments)
        )

    except FileExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """
    Get service status and queue depth.

    Returns:
        Service status information
    """
    pipe = get_pipeline()
    ollama_connected = await pipe.check_ollama_health()

    return StatusResponse(
        status="healthy" if ollama_connected else "degraded",
        ollama_connected=ollama_connected,
        ollama_model=settings.ollama_model,
        queue_depth=0,  # TODO: Implement queue tracking
        crawler=CrawlerStatus(
            enabled=settings.crawler_enabled,
            last_run=None,  # TODO: Track crawler runs
            videos_found=0,
            videos_pending=0
        )
    )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Simple health check for container orchestration.

    Returns:
        Health status
    """
    return HealthResponse(healthy=True)


@router.post("/crawler/trigger", response_model=CrawlerTriggerResponse)
async def trigger_crawler():
    """
    Manually trigger a crawler run (if crawler enabled).

    Returns:
        Crawler trigger result

    Raises:
        HTTPException: If crawler is not enabled
    """
    if not settings.crawler_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Crawler is not enabled"
        )

    # TODO: Implement crawler triggering
    return CrawlerTriggerResponse(
        triggered=True,
        videos_queued=0
    )


@router.get("/video/{path:path}/metadata")
async def get_video_metadata(path: str):
    """
    Retrieve existing metadata for a video without re-analyzing.

    Args:
        path: Video file path

    Returns:
        Metadata JSON

    Raises:
        HTTPException: If metadata not found
    """
    sidecar_path = path + ".meta.json"

    if not os.path.exists(sidecar_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Metadata not found for: {path}"
        )

    try:
        with open(sidecar_path, "r") as f:
            metadata = json.load(f)
        return JSONResponse(content=metadata)
    except Exception as e:
        logger.error(f"Error reading metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading metadata: {str(e)}"
        )
