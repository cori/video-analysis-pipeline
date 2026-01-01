"""Ollama vision model integration for frame analysis."""

import base64
import json
import logging
from typing import Optional, List
import httpx

from src.config import settings
from src.models.schema import FrameAnalysis
from src.analysis.frames import Frame

logger = logging.getLogger(__name__)


FRAME_ANALYSIS_SYSTEM_PROMPT = """You are analyzing frames from FPV drone footage. Describe what you see concisely, focusing on:
- Environment (indoor/outdoor, terrain type, vegetation, structures)
- Flight characteristics (speed impression, proximity to objects, altitude)
- Maneuvers if identifiable (rolls, flips, split-s, gaps, proximity)
- Visual quality (clear, foggy, DVR artifacts, signal breakup)
- Notable features (interesting scenery, obstacles, other pilots)

Respond in JSON format with these exact fields:
{
  "description": "Brief description of the scene",
  "environment": ["outdoor", "forest"],
  "flight_style": "proximity",
  "interest_score": 7,
  "quality_issues": []
}

Where:
- description: 1-2 sentence description
- environment: list of environment tags (outdoor, indoor, forest, field, urban, etc.)
- flight_style: one of: takeoff, landing, cruising, proximity, freestyle, racing, cinematic, stationary
- interest_score: 1-10 rating (1=boring, 10=amazing)
- quality_issues: list of issues like "dvr-artifacts", "signal-loss", "blur", "foggy", or empty list
"""

SUMMARY_GENERATION_PROMPT = """Based on these frame-by-frame descriptions of an FPV drone flight, write a 2-3 sentence summary.

Frame descriptions:
{frame_descriptions}

Focus on: overall environment, flight style, and any notable moments.
Respond with just the summary text, no JSON or extra formatting."""


class OllamaVisionClient:
    """Client for Ollama vision API."""

    def __init__(self, host: str = None, model: str = None, timeout: int = None):
        self.host = host or settings.ollama_host
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def health_check(self) -> bool:
        """
        Check if Ollama is accessible.

        Returns:
            True if Ollama is healthy, False otherwise
        """
        try:
            response = await self.client.get(f"{self.host}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def get_available_models(self) -> List[str]:
        """
        Get list of available models.

        Returns:
            List of model names
        """
        try:
            response = await self.client.get(f"{self.host}/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
            return []
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return []

    def _encode_image(self, image_path: str) -> str:
        """
        Encode image to base64.

        Args:
            image_path: Path to image file

        Returns:
            Base64 encoded image
        """
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def analyze_frame(self, frame: Frame) -> FrameAnalysis:
        """
        Analyze a single frame using Ollama vision model.

        Args:
            frame: Frame to analyze

        Returns:
            FrameAnalysis with extracted information
        """
        try:
            # Encode image
            image_b64 = self._encode_image(frame.image_path)

            # Prepare request
            request_data = {
                "model": self.model,
                "prompt": FRAME_ANALYSIS_SYSTEM_PROMPT,
                "images": [image_b64],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 256
                }
            }

            logger.debug(f"Analyzing frame at {frame.timestamp}s")

            # Make request
            response = await self.client.post(
                f"{self.host}/api/generate",
                json=request_data
            )

            if response.status_code != 200:
                raise RuntimeError(f"Ollama API error: {response.status_code} - {response.text}")

            result = response.json()
            response_text = result.get("response", "{}")

            # Parse JSON response
            try:
                analysis_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON response: {response_text}")
                # Provide defaults
                analysis_data = {
                    "description": "Unable to analyze frame",
                    "environment": [],
                    "flight_style": "unknown",
                    "interest_score": 5,
                    "quality_issues": []
                }

            # Create FrameAnalysis object
            return FrameAnalysis(
                timestamp=frame.timestamp,
                description=analysis_data.get("description", ""),
                environment=analysis_data.get("environment", []),
                flight_style=analysis_data.get("flight_style", "unknown"),
                interest_score=min(10, max(1, analysis_data.get("interest_score", 5))),
                quality_issues=analysis_data.get("quality_issues", [])
            )

        except Exception as e:
            logger.error(f"Error analyzing frame at {frame.timestamp}s: {e}")
            # Return minimal analysis on error
            return FrameAnalysis(
                timestamp=frame.timestamp,
                description="Error analyzing frame",
                environment=[],
                flight_style="unknown",
                interest_score=5,
                quality_issues=["analysis-error"]
            )

    async def generate_summary(self, frame_analyses: List[FrameAnalysis]) -> str:
        """
        Generate overall summary from frame analyses.

        Args:
            frame_analyses: List of frame analyses

        Returns:
            Summary text
        """
        try:
            # Build frame descriptions
            descriptions = []
            for fa in frame_analyses:
                descriptions.append(f"- [{fa.timestamp:.1f}s] {fa.description}")

            frame_desc_text = "\n".join(descriptions[:50])  # Limit to 50 frames

            prompt = SUMMARY_GENERATION_PROMPT.format(frame_descriptions=frame_desc_text)

            request_data = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.5,
                    "num_predict": 128
                }
            }

            response = await self.client.post(
                f"{self.host}/api/generate",
                json=request_data
            )

            if response.status_code != 200:
                raise RuntimeError(f"Ollama API error: {response.status_code}")

            result = response.json()
            summary = result.get("response", "").strip()

            logger.info(f"Generated summary: {summary}")
            return summary

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "Unable to generate summary."

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
