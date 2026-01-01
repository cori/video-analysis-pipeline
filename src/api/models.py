"""API request and response models."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class AnalysisOptions(BaseModel):
    """Options for video analysis."""
    generate_xmp: bool = False
    trim_static: bool = False


class AnalyzeRequest(BaseModel):
    """Request to analyze a video."""
    path: str = Field(..., description="Absolute path to video file")
    force: bool = Field(False, description="Re-analyze even if sidecar exists")
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


class AnalyzeResponse(BaseModel):
    """Response from video analysis."""
    status: str
    path: str
    sidecar: str
    duration_seconds: float
    tags: List[str]
    highlights_count: int
    static_segments_count: int


class CrawlerStatus(BaseModel):
    """Crawler status information."""
    enabled: bool
    last_run: Optional[datetime] = None
    videos_found: int = 0
    videos_pending: int = 0


class StatusResponse(BaseModel):
    """Service status response."""
    status: str
    ollama_connected: bool
    ollama_model: str
    queue_depth: int
    crawler: CrawlerStatus


class HealthResponse(BaseModel):
    """Health check response."""
    healthy: bool


class CrawlerTriggerResponse(BaseModel):
    """Crawler trigger response."""
    triggered: bool
    videos_queued: int
