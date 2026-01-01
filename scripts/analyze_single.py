#!/usr/bin/env python3
"""CLI script to analyze a single video file."""

import asyncio
import sys
import os
import argparse

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analysis.pipeline import AnalysisPipeline


async def main():
    """Analyze a single video."""
    parser = argparse.ArgumentParser(description="Analyze an FPV video file")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force re-analysis even if sidecar exists"
    )

    args = parser.parse_args()

    # Validate video exists
    if not os.path.exists(args.video_path):
        print(f"❌ Error: Video file not found: {args.video_path}")
        sys.exit(1)

    print(f"Analyzing video: {args.video_path}")
    print()

    # Create pipeline
    pipeline = AnalysisPipeline()

    # Check Ollama
    print("Checking Ollama connection...")
    if not await pipeline.check_ollama_health():
        print("❌ Error: Ollama is not accessible")
        await pipeline.close()
        sys.exit(1)
    print("✅ Ollama is ready")
    print()

    # Run analysis
    try:
        metadata = await pipeline.analyze_video(args.video_path, force=args.force)

        print()
        print("=" * 60)
        print("Analysis Complete!")
        print("=" * 60)
        print(f"Duration: {metadata.source.duration_seconds:.1f}s")
        print(f"Frames analyzed: {metadata.analysis.frames_analyzed}")
        print(f"Analysis time: {metadata.analysis.analysis_duration_seconds:.1f}s")
        print()
        print(f"Tags ({len(metadata.tags)}): {', '.join(metadata.tags)}")
        print()
        print(f"Static segments: {len(metadata.static_segments)}")
        for seg in metadata.static_segments:
            print(f"  - {seg.start:.1f}s - {seg.end:.1f}s: {seg.reason.value}")
        print()
        print(f"Highlights: {len(metadata.highlights)}")
        for hl in metadata.highlights:
            print(f"  - {hl.start:.1f}s - {hl.end:.1f}s (score: {hl.score}): {hl.description}")
        print()
        print(f"Summary: {metadata.summary}")
        print()
        print(f"Quality score: {metadata.quality.overall_score}/10")
        print()
        print(f"Sidecar written to: {args.video_path}.meta.json")
        print("=" * 60)

    except FileExistsError:
        print(f"⚠️  Sidecar already exists. Use --force to re-analyze.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await pipeline.close()


if __name__ == "__main__":
    asyncio.run(main())
