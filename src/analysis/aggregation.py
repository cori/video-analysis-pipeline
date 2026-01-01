"""Aggregation of frame analyses into highlights and tags."""

import logging
from collections import Counter
from typing import List, Tuple

from src.config import settings
from src.models.schema import FrameAnalysis, Highlight, QualityMetadata

logger = logging.getLogger(__name__)


class Aggregator:
    """Aggregate frame analyses into higher-level metadata."""

    def __init__(
        self,
        tag_threshold: float = None,
        highlight_score_threshold: int = None,
        highlight_min_duration: float = None
    ):
        self.tag_threshold = tag_threshold or settings.tag_frequency_threshold
        self.highlight_score_threshold = highlight_score_threshold or settings.highlight_score_threshold
        self.highlight_min_duration = highlight_min_duration or settings.highlight_min_duration

    def extract_tags(self, frame_analyses: List[FrameAnalysis]) -> List[str]:
        """
        Extract common tags from frame analyses.

        Args:
            frame_analyses: List of frame analyses

        Returns:
            List of tags that appear frequently
        """
        if not frame_analyses:
            return []

        # Collect all tags
        tag_counter = Counter()

        for fa in frame_analyses:
            # Count environment tags
            for tag in fa.environment:
                tag_counter[tag] += 1

            # Count flight style if meaningful
            if fa.flight_style and fa.flight_style not in ["unknown", "stationary"]:
                tag_counter[fa.flight_style] += 1

        # Filter tags by frequency threshold
        total_frames = len(frame_analyses)
        threshold_count = int(total_frames * self.tag_threshold)

        tags = [tag for tag, count in tag_counter.items() if count >= threshold_count]

        # Sort by frequency
        tags.sort(key=lambda t: tag_counter[t], reverse=True)

        logger.info(f"Extracted {len(tags)} tags from {total_frames} frames: {tags}")
        return tags

    def detect_highlights(self, frame_analyses: List[FrameAnalysis]) -> List[Highlight]:
        """
        Detect highlight segments based on interest scores.

        Args:
            frame_analyses: List of frame analyses

        Returns:
            List of highlight segments
        """
        if not frame_analyses:
            return []

        highlights = []
        in_highlight = False
        highlight_start = 0.0
        highlight_frames = []

        logger.info(f"Detecting highlights with score threshold {self.highlight_score_threshold}")

        for i, fa in enumerate(frame_analyses):
            if fa.interest_score >= self.highlight_score_threshold:
                if not in_highlight:
                    in_highlight = True
                    highlight_start = fa.timestamp
                    highlight_frames = [fa]
                else:
                    highlight_frames.append(fa)
            else:
                if in_highlight:
                    # End of highlight segment
                    highlight_end = frame_analyses[i - 1].timestamp
                    duration = highlight_end - highlight_start

                    if duration >= self.highlight_min_duration:
                        highlight = self._create_highlight(
                            highlight_start,
                            highlight_end,
                            highlight_frames
                        )
                        highlights.append(highlight)

                    in_highlight = False
                    highlight_frames = []

        # Handle case where video ends in a highlight
        if in_highlight:
            highlight_end = frame_analyses[-1].timestamp
            duration = highlight_end - highlight_start

            if duration >= self.highlight_min_duration:
                highlight = self._create_highlight(
                    highlight_start,
                    highlight_end,
                    highlight_frames
                )
                highlights.append(highlight)

        logger.info(f"Detected {len(highlights)} highlights")
        return highlights

    def _create_highlight(
        self,
        start: float,
        end: float,
        frames: List[FrameAnalysis]
    ) -> Highlight:
        """
        Create a highlight from a segment of frames.

        Args:
            start: Start timestamp
            end: End timestamp
            frames: Frames in the highlight

        Returns:
            Highlight object
        """
        # Calculate average score
        avg_score = sum(f.interest_score for f in frames) // len(frames)

        # Collect tags from frames
        tag_counter = Counter()
        for f in frames:
            for tag in f.environment:
                tag_counter[tag] += 1
            if f.flight_style and f.flight_style not in ["unknown", "stationary"]:
                tag_counter[f.flight_style] += 1

        # Get top tags
        top_tags = [tag for tag, _ in tag_counter.most_common(5)]

        # Create description from the frame with highest score
        best_frame = max(frames, key=lambda f: f.interest_score)
        description = best_frame.description

        return Highlight(
            start=start,
            end=end,
            score=avg_score,
            description=description,
            tags=top_tags
        )

    def assess_quality(self, frame_analyses: List[FrameAnalysis]) -> QualityMetadata:
        """
        Assess overall video quality based on frame analyses.

        Args:
            frame_analyses: List of frame analyses

        Returns:
            QualityMetadata with quality assessment
        """
        if not frame_analyses:
            return QualityMetadata()

        # Collect all quality issues
        all_issues = []
        dvr_artifacts_detected = False
        signal_loss_segments = []

        issue_counter = Counter()

        for fa in frame_analyses:
            for issue in fa.quality_issues:
                issue_counter[issue] += 1

                if "dvr" in issue.lower() or "artifact" in issue.lower():
                    dvr_artifacts_detected = True

                if "signal" in issue.lower() or "loss" in issue.lower():
                    signal_loss_segments.append({
                        "start": fa.timestamp,
                        "end": fa.timestamp + 1.0  # Approximate
                    })

        # Get significant issues (appear in >10% of frames)
        total_frames = len(frame_analyses)
        threshold = max(1, int(total_frames * 0.1))

        significant_issues = [
            issue for issue, count in issue_counter.items()
            if count >= threshold
        ]

        # Calculate overall quality score
        # Start at 10, deduct points for issues
        overall_score = 10

        for issue in significant_issues:
            if "blur" in issue.lower():
                overall_score -= 2
            elif "artifact" in issue.lower() or "dvr" in issue.lower():
                overall_score -= 3
            elif "signal" in issue.lower() or "loss" in issue.lower():
                overall_score -= 4
            elif "fog" in issue.lower() or "weather" in issue.lower():
                overall_score -= 1

        overall_score = max(1, min(10, overall_score))

        logger.info(f"Quality assessment: score={overall_score}, issues={significant_issues}")

        return QualityMetadata(
            overall_score=overall_score,
            issues=significant_issues,
            dvr_artifacts_detected=dvr_artifacts_detected,
            signal_loss_segments=signal_loss_segments
        )
