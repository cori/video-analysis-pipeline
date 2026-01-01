"""Configuration management for FPV Video Analyzer."""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Ollama configuration
    ollama_host: str = "http://host.docker.internal:11434"
    ollama_model: str = "llava:13b"
    ollama_timeout: int = 300  # seconds

    # Crawler configuration
    crawler_enabled: bool = False
    crawler_root: str = "/videos"
    crawler_interval: int = 3600  # seconds

    # Analysis parameters
    frame_sample_interval: float = 2.0  # seconds
    static_threshold: float = 0.02  # frame difference threshold
    max_frames_per_video: int = 100
    min_static_duration: float = 1.0  # seconds

    # Highlight detection
    highlight_score_threshold: int = 7
    highlight_min_duration: float = 5.0  # seconds
    tag_frequency_threshold: float = 0.2  # 20% of frames

    # Processing configuration
    max_concurrent_analyses: int = 1
    analysis_pause_seconds: int = 30

    # Server configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8420
    log_level: str = "INFO"

    # Application metadata
    app_version: str = "0.1.0"
    schema_version: str = "1.0"

    class Config:
        """Pydantic config."""
        env_file = ".env"
        case_sensitive = False
        # Map environment variables to snake_case
        env_prefix = ""


# Global settings instance
settings = Settings()
