"""Pydantic models for video metadata sidecar schema."""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """Video source type."""
    ONBOARD = "onboard"
    DVR = "dvr"
    UNKNOWN = "unknown"


class StaticReason(str, Enum):
    """Reason for static segment."""
    PRE_ARM = "pre-arm"
    POST_LAND = "post-land"
    DVR_FREEZE = "dvr-freeze"
    SIGNAL_LOSS = "signal-loss"
    UNKNOWN = "unknown"


class SourceMetadata(BaseModel):
    """Source video metadata."""
    filename: str
    duration_seconds: float
    resolution: List[int] = Field(default_factory=lambda: [0, 0])
    framerate: float = 0.0
    codec: str = ""
    file_size_bytes: int = 0
    creation_time: Optional[datetime] = None
    source_type: SourceType = SourceType.UNKNOWN


class AnalysisMetadata(BaseModel):
    """Analysis process metadata."""
    frames_analyzed: int = 0
    analysis_duration_seconds: float = 0.0


class StaticSegment(BaseModel):
    """Static video segment."""
    start: float
    end: float
    reason: StaticReason
    confidence: float = Field(ge=0.0, le=1.0)


class Highlight(BaseModel):
    """Video highlight segment."""
    start: float
    end: float
    score: int = Field(ge=1, le=10)
    description: str
    tags: List[str] = Field(default_factory=list)


class FrameAnalysis(BaseModel):
    """Individual frame analysis result."""
    timestamp: float
    description: str
    environment: List[str] = Field(default_factory=list)
    flight_style: str = ""
    interest_score: int = Field(ge=1, le=10)
    quality_issues: List[str] = Field(default_factory=list)


class QualityMetadata(BaseModel):
    """Video quality assessment."""
    overall_score: int = Field(ge=1, le=10, default=5)
    issues: List[str] = Field(default_factory=list)
    dvr_artifacts_detected: bool = False
    signal_loss_segments: List[Dict[str, float]] = Field(default_factory=list)


class VideoMetadata(BaseModel):
    """Complete video metadata sidecar."""
    schema_version: str = "1.0"
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    analyzer_version: str
    ollama_model: str

    source: SourceMetadata
    analysis: AnalysisMetadata

    tags: List[str] = Field(default_factory=list)
    summary: str = ""

    static_segments: List[StaticSegment] = Field(default_factory=list)
    highlights: List[Highlight] = Field(default_factory=list)
    frame_analysis: List[FrameAnalysis] = Field(default_factory=list)

    quality: QualityMetadata = Field(default_factory=QualityMetadata)
    custom: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        """Pydantic config."""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() + "Z" if v else None
        }
