"""Static segment detection for FPV footage."""

import logging
from typing import List
import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

from src.config import settings
from src.models.schema import StaticSegment, StaticReason
from src.analysis.frames import Frame

logger = logging.getLogger(__name__)


class StaticDetector:
    """Detect static segments in video footage."""

    def __init__(self, threshold: float = None, min_duration: float = None):
        self.threshold = threshold or settings.static_threshold
        self.min_duration = min_duration or settings.min_static_duration

    def compute_frame_difference(self, frame1: Frame, frame2: Frame) -> float:
        """
        Compute difference between two frames using SSIM.

        Args:
            frame1: First frame
            frame2: Second frame

        Returns:
            Difference score (0 = identical, 1 = completely different)
        """
        # Get grayscale versions
        gray1 = frame1.get_grayscale()
        gray2 = frame2.get_grayscale()

        # Downsample for faster comparison
        scale = 0.25
        small1 = cv2.resize(gray1, None, fx=scale, fy=scale)
        small2 = cv2.resize(gray2, None, fx=scale, fy=scale)

        # Compute SSIM
        score, _ = ssim(small1, small2, full=True)

        # Convert SSIM (1 = identical) to difference (0 = identical)
        return 1.0 - score

    def classify_static(self, start: float, end: float, video_duration: float) -> StaticReason:
        """
        Classify why a segment is static based on its position in the video.

        Args:
            start: Segment start time in seconds
            end: Segment end time in seconds
            video_duration: Total video duration in seconds

        Returns:
            StaticReason classification
        """
        # First 30 seconds
        if start < 30:
            return StaticReason.PRE_ARM

        # Last 30 seconds
        if end > video_duration - 30:
            return StaticReason.POST_LAND

        # Middle of video - likely DVR freeze or pause
        return StaticReason.DVR_FREEZE

    def detect_static_segments(
        self,
        frames: List[Frame],
        video_duration: float
    ) -> List[StaticSegment]:
        """
        Detect static segments using frame differencing.

        Args:
            frames: List of frames with timestamps
            video_duration: Total video duration in seconds

        Returns:
            List of static segments with start/end times and classification
        """
        if len(frames) < 2:
            logger.warning("Not enough frames for static detection")
            return []

        logger.info(f"Detecting static segments with threshold {self.threshold}")

        segments = []
        in_static = False
        static_start = 0.0

        for i in range(1, len(frames)):
            # Compare frames
            diff = self.compute_frame_difference(frames[i - 1], frames[i])

            if diff < self.threshold:
                if not in_static:
                    in_static = True
                    static_start = frames[i - 1].timestamp
                    logger.debug(f"Static segment started at {static_start}s (diff: {diff:.4f})")
            else:
                if in_static:
                    static_end = frames[i].timestamp
                    duration = static_end - static_start

                    if duration >= self.min_duration:
                        reason = self.classify_static(static_start, static_end, video_duration)

                        # Calculate confidence based on consistency of low difference
                        confidence = 1.0 - (diff / self.threshold)
                        confidence = max(0.0, min(1.0, confidence))

                        segment = StaticSegment(
                            start=static_start,
                            end=static_end,
                            reason=reason,
                            confidence=confidence
                        )
                        segments.append(segment)
                        logger.info(
                            f"Detected {reason.value} segment: {static_start:.1f}s - {static_end:.1f}s "
                            f"(duration: {duration:.1f}s, confidence: {confidence:.2f})"
                        )

                    in_static = False

        # Handle case where video ends in static
        if in_static:
            static_end = frames[-1].timestamp
            duration = static_end - static_start

            if duration >= self.min_duration:
                reason = self.classify_static(static_start, static_end, video_duration)
                segment = StaticSegment(
                    start=static_start,
                    end=static_end,
                    reason=reason,
                    confidence=0.9
                )
                segments.append(segment)

        logger.info(f"Detected {len(segments)} static segments")
        return segments

    def compute_mean_difference(self, frame1: Frame, frame2: Frame) -> float:
        """
        Alternative: Compute mean absolute difference between frames.

        Args:
            frame1: First frame
            frame2: Second frame

        Returns:
            Normalized mean absolute difference (0-1)
        """
        gray1 = frame1.get_grayscale()
        gray2 = frame2.get_grayscale()

        # Downsample
        scale = 0.25
        small1 = cv2.resize(gray1, None, fx=scale, fy=scale)
        small2 = cv2.resize(gray2, None, fx=scale, fy=scale)

        # Compute mean absolute difference
        diff = np.abs(small1.astype(float) - small2.astype(float))
        mean_diff = np.mean(diff) / 255.0

        return mean_diff
