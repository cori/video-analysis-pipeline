"""Frame extraction and management for video analysis."""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from src.config import settings
from src.models.schema import SourceMetadata, SourceType

logger = logging.getLogger(__name__)


class Frame:
    """Represents a single video frame."""

    def __init__(self, timestamp: float, image_path: str, data: Optional[np.ndarray] = None):
        self.timestamp = timestamp
        self.image_path = image_path
        self._data = data

    @property
    def data(self) -> np.ndarray:
        """Lazy load frame data."""
        if self._data is None:
            self._data = cv2.imread(self.image_path)
        return self._data

    def get_grayscale(self) -> np.ndarray:
        """Get grayscale version of frame."""
        if len(self.data.shape) == 3:
            return cv2.cvtColor(self.data, cv2.COLOR_BGR2GRAY)
        return self.data


class VideoProbe:
    """Extract video metadata using ffprobe."""

    @staticmethod
    async def probe(video_path: str) -> SourceMetadata:
        """
        Extract video metadata using ffprobe.

        Args:
            video_path: Path to video file

        Returns:
            SourceMetadata with video information
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video_path
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

            probe_data = json.loads(stdout.decode())

            # Find video stream
            video_stream = None
            for stream in probe_data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if not video_stream:
                raise ValueError("No video stream found")

            # Extract metadata
            format_data = probe_data.get("format", {})

            # Get file stats
            file_stat = os.stat(video_path)

            # Parse creation time if available
            creation_time = None
            creation_time_str = format_data.get("tags", {}).get("creation_time")
            if creation_time_str:
                try:
                    from datetime import datetime
                    creation_time = datetime.fromisoformat(creation_time_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            # Determine source type based on resolution and codec
            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))
            source_type = SourceType.UNKNOWN

            # Common DVR resolutions are lower (720p, 480p)
            # Onboard HD is typically 1080p or higher
            if height >= 1080:
                source_type = SourceType.ONBOARD
            elif height > 0:
                source_type = SourceType.DVR

            return SourceMetadata(
                filename=os.path.basename(video_path),
                duration_seconds=float(format_data.get("duration", 0)),
                resolution=[width, height],
                framerate=eval(video_stream.get("r_frame_rate", "0/1")),
                codec=video_stream.get("codec_name", ""),
                file_size_bytes=file_stat.st_size,
                creation_time=creation_time,
                source_type=source_type
            )

        except Exception as e:
            logger.error(f"Error probing video {video_path}: {e}")
            raise


class FrameExtractor:
    """Extract frames from video for analysis."""

    def __init__(self, sample_interval: float = None, max_frames: int = None):
        self.sample_interval = sample_interval or settings.frame_sample_interval
        self.max_frames = max_frames or settings.max_frames_per_video

    async def extract_frames(self, video_path: str, output_dir: str) -> List[Frame]:
        """
        Extract frames from video using ffmpeg.

        Args:
            video_path: Path to video file
            output_dir: Directory to save extracted frames

        Returns:
            List of Frame objects
        """
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Extracting frames from {video_path} with interval {self.sample_interval}s")

        # Build ffmpeg command for frame extraction
        # Extract frames at regular intervals, scale to reasonable size
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{self.sample_interval})',scale=1280:-1",
            "-vsync", "vfr",
            "-q:v", "2",
            "-frames:v", str(self.max_frames),
            os.path.join(output_dir, "frame_%04d.jpg")
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"ffmpeg frame extraction failed: {stderr.decode()}")

            # Get list of extracted frames and their timestamps
            frames = []
            frame_files = sorted([f for f in os.listdir(output_dir) if f.startswith("frame_")])

            # Calculate timestamps based on frame order and sample interval
            for i, frame_file in enumerate(frame_files):
                timestamp = i * self.sample_interval
                frame_path = os.path.join(output_dir, frame_file)
                frames.append(Frame(timestamp=timestamp, image_path=frame_path))

            logger.info(f"Extracted {len(frames)} frames from video")
            return frames

        except Exception as e:
            logger.error(f"Error extracting frames: {e}")
            raise

    async def extract_frames_opencv(self, video_path: str, output_dir: str) -> List[Frame]:
        """
        Alternative: Extract frames using OpenCV (for better timestamp accuracy).

        Args:
            video_path: Path to video file
            output_dir: Directory to save extracted frames

        Returns:
            List of Frame objects
        """
        os.makedirs(output_dir, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        frame_interval = int(fps * self.sample_interval)
        frames = []
        frame_count = 0
        saved_count = 0

        logger.info(f"Extracting frames from {video_path} (FPS: {fps}, Duration: {duration}s)")

        try:
            while cap.isOpened() and saved_count < self.max_frames:
                ret, frame_data = cap.read()
                if not ret:
                    break

                if frame_count % frame_interval == 0 or frame_count == 0:
                    timestamp = frame_count / fps
                    frame_filename = f"frame_{saved_count:04d}.jpg"
                    frame_path = os.path.join(output_dir, frame_filename)

                    # Resize frame to reduce size
                    height, width = frame_data.shape[:2]
                    if width > 1280:
                        scale = 1280 / width
                        new_width = 1280
                        new_height = int(height * scale)
                        frame_data = cv2.resize(frame_data, (new_width, new_height))

                    cv2.imwrite(frame_path, frame_data)
                    frames.append(Frame(timestamp=timestamp, image_path=frame_path, data=frame_data))
                    saved_count += 1

                frame_count += 1

        finally:
            cap.release()

        logger.info(f"Extracted {len(frames)} frames using OpenCV")
        return frames
