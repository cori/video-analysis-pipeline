"""Main analysis pipeline orchestrating all components."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import settings
from src.models.schema import (
    VideoMetadata,
    SourceMetadata,
    AnalysisMetadata,
    FrameAnalysis,
)
from src.analysis.frames import VideoProbe, FrameExtractor, Frame
from src.analysis.static import StaticDetector
from src.analysis.vision import OllamaVisionClient
from src.analysis.aggregation import Aggregator

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Main pipeline for video analysis."""

    def __init__(self):
        self.video_probe = VideoProbe()
        self.frame_extractor = FrameExtractor()
        self.static_detector = StaticDetector()
        self.vision_client = OllamaVisionClient()
        self.aggregator = Aggregator()

    async def analyze_video(
        self,
        video_path: str,
        force: bool = False
    ) -> VideoMetadata:
        """
        Analyze a video file and generate metadata.

        Args:
            video_path: Path to video file
            force: Re-analyze even if sidecar exists

        Returns:
            VideoMetadata object

        Raises:
            FileNotFoundError: If video doesn't exist
            RuntimeError: If analysis fails
        """
        # Validate video exists
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        # Check for existing sidecar
        sidecar_path = video_path + ".meta.json"
        if os.path.exists(sidecar_path) and not force:
            logger.info(f"Sidecar already exists for {video_path}, skipping")
            raise FileExistsError(f"Sidecar exists: {sidecar_path}")

        logger.info(f"Starting analysis of {video_path}")
        start_time = time.time()

        temp_dir = None
        try:
            # Stage 1: Video Probe
            logger.info("Stage 1: Probing video metadata")
            source_metadata = await self.video_probe.probe(video_path)
            logger.info(
                f"Video: {source_metadata.duration_seconds:.1f}s, "
                f"{source_metadata.resolution[0]}x{source_metadata.resolution[1]}, "
                f"{source_metadata.codec}"
            )

            # Stage 2: Frame Extraction
            logger.info("Stage 2: Extracting frames")
            temp_dir = tempfile.mkdtemp(prefix="fpv_analysis_")
            frames = await self.frame_extractor.extract_frames_opencv(video_path, temp_dir)

            if not frames:
                raise RuntimeError("No frames extracted from video")

            logger.info(f"Extracted {len(frames)} frames")

            # Stage 3: Static Detection
            logger.info("Stage 3: Detecting static segments")
            static_segments = self.static_detector.detect_static_segments(
                frames,
                source_metadata.duration_seconds
            )

            # Stage 4: Frame Analysis via LLM
            logger.info("Stage 4: Analyzing frames with vision model")
            frame_analyses = await self._analyze_frames(frames)

            # Stage 5: Aggregation
            logger.info("Stage 5: Aggregating results")
            tags = self.aggregator.extract_tags(frame_analyses)
            highlights = self.aggregator.detect_highlights(frame_analyses)
            quality = self.aggregator.assess_quality(frame_analyses)

            # Stage 6: Summary Generation
            logger.info("Stage 6: Generating summary")
            summary = await self.vision_client.generate_summary(frame_analyses)

            # Calculate analysis duration
            analysis_duration = time.time() - start_time

            # Build metadata object
            metadata = VideoMetadata(
                schema_version=settings.schema_version,
                analyzed_at=datetime.utcnow(),
                analyzer_version=settings.app_version,
                ollama_model=settings.ollama_model,
                source=source_metadata,
                analysis=AnalysisMetadata(
                    frames_analyzed=len(frames),
                    analysis_duration_seconds=analysis_duration
                ),
                tags=tags,
                summary=summary,
                static_segments=static_segments,
                highlights=highlights,
                frame_analysis=frame_analyses,
                quality=quality
            )

            # Stage 7: Write sidecar
            logger.info(f"Writing metadata to {sidecar_path}")
            await self._write_sidecar(metadata, sidecar_path)

            logger.info(
                f"Analysis complete in {analysis_duration:.1f}s: "
                f"{len(tags)} tags, {len(highlights)} highlights, "
                f"{len(static_segments)} static segments"
            )

            return metadata

        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            raise

        finally:
            # Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temp directory: {temp_dir}")

    async def _analyze_frames(self, frames: list[Frame]) -> list[FrameAnalysis]:
        """
        Analyze all frames using vision model.

        Args:
            frames: List of frames to analyze

        Returns:
            List of frame analyses
        """
        frame_analyses = []

        # Analyze frames sequentially to avoid overwhelming Ollama
        for i, frame in enumerate(frames):
            logger.info(f"Analyzing frame {i + 1}/{len(frames)} at {frame.timestamp:.1f}s")

            try:
                analysis = await self.vision_client.analyze_frame(frame)
                frame_analyses.append(analysis)
            except Exception as e:
                logger.warning(f"Failed to analyze frame at {frame.timestamp}s: {e}")
                # Create minimal analysis on error
                frame_analyses.append(
                    FrameAnalysis(
                        timestamp=frame.timestamp,
                        description="Analysis failed",
                        environment=[],
                        flight_style="unknown",
                        interest_score=5,
                        quality_issues=["analysis-error"]
                    )
                )

        return frame_analyses

    async def _write_sidecar(self, metadata: VideoMetadata, sidecar_path: str):
        """
        Write metadata to JSON sidecar file.

        Args:
            metadata: VideoMetadata to write
            sidecar_path: Path to sidecar file
        """
        # Convert to dict with proper serialization
        metadata_dict = metadata.model_dump(mode="json")

        # Write to file
        with open(sidecar_path, "w") as f:
            json.dump(metadata_dict, f, indent=2, ensure_ascii=False)

        logger.info(f"Wrote sidecar: {sidecar_path}")

    async def check_ollama_health(self) -> bool:
        """
        Check if Ollama is available.

        Returns:
            True if healthy, False otherwise
        """
        return await self.vision_client.health_check()

    async def close(self):
        """Cleanup resources."""
        await self.vision_client.close()
