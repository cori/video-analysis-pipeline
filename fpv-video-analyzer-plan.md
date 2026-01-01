# FPV Video Analyzer

A containerized service for analyzing drone footage using local LLMs, designed to run on UnifyDrive UT4 with Ollama.

## Overview

This system provides automated analysis of FPV drone footage, generating structured metadata sidecars with tags, summaries, highlight markers, and static segment detection. It operates as a Docker container exposing an HTTP API and optionally crawls a directory tree for unprocessed videos.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    UnifyDrive UT4                               │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────────────────────────┐  │
│  │   FileFlows  │───▶│       fpv-video-analyzer             │  │
│  │  (existing)  │    │                                      │  │
│  └──────────────┘    │  ┌────────────┐  ┌───────────────┐   │  │
│                      │  │ HTTP API   │  │ Crawler       │   │  │
│  ┌──────────────┐    │  │ :8420      │  │ (optional)    │   │  │
│  │   Ollama     │◀───│  └────────────┘  └───────────────┘   │  │
│  │  llava:13b   │    │           │                          │  │
│  │  (16GB VRAM) │    │           ▼                          │  │
│  └──────────────┘    │  ┌────────────────────────────────┐  │  │
│                      │  │ Analysis Pipeline              │  │  │
│                      │  │ FFmpeg → OpenCV → Ollama → JSON│  │  │
│                      │  └────────────────────────────────┘  │  │
│                      └──────────────────────────────────────┘  │
│                                                                 │
│  /storage/videos/                                               │
│  └── 2025-01-15/                                               │
│      ├── flight_001.mp4                                        │
│      └── flight_001.mp4.meta.json  ← generated                 │
└─────────────────────────────────────────────────────────────────┘
```

## Container Specification

### Image

- **Base**: `python:3.11-slim`
- **Additional packages**: ffmpeg, opencv dependencies
- **Python dependencies**: fastapi, uvicorn, httpx, opencv-python-headless, numpy

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llava:13b` | Vision model to use |
| `CRAWLER_ENABLED` | `false` | Enable background directory crawler |
| `CRAWLER_ROOT` | `/videos` | Root path for crawler to scan |
| `CRAWLER_INTERVAL` | `3600` | Seconds between crawler runs |
| `FRAME_SAMPLE_INTERVAL` | `2.0` | Seconds between sampled frames |
| `STATIC_THRESHOLD` | `0.02` | Frame difference threshold for static detection |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Volumes

| Container Path | Purpose |
|----------------|---------|
| `/videos` | Video storage root (read/write for sidecars) |
| `/config` | Optional persistent configuration |

### Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 8420 | HTTP | API endpoint |

## HTTP API

### POST /analyze

Analyze a single video file and generate metadata sidecar.

**Request**
```json
{
  "path": "/videos/2025-01-15/flight_001.mp4",
  "force": false,
  "options": {
    "generate_xmp": false,
    "trim_static": false
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Absolute path to video file |
| `force` | boolean | no | Re-analyze even if sidecar exists |
| `options.generate_xmp` | boolean | no | Also write XMP sidecar via exiftool |
| `options.trim_static` | boolean | no | Create trimmed copy removing static segments |

**Response**
```json
{
  "status": "complete",
  "path": "/videos/2025-01-15/flight_001.mp4",
  "sidecar": "/videos/2025-01-15/flight_001.mp4.meta.json",
  "duration_seconds": 142.5,
  "tags": ["outdoor", "trees", "proximity"],
  "highlights_count": 3,
  "static_segments_count": 2
}
```

**Status Codes**
- `200` - Analysis complete
- `202` - Analysis queued (async mode)
- `400` - Invalid request (file not found, not a video, etc.)
- `409` - Sidecar exists and force=false
- `500` - Analysis failed
- `503` - Ollama unavailable

### GET /status

Get service status and queue depth.

**Response**
```json
{
  "status": "healthy",
  "ollama_connected": true,
  "ollama_model": "llava:13b",
  "queue_depth": 2,
  "crawler": {
    "enabled": true,
    "last_run": "2025-01-15T10:30:00Z",
    "videos_found": 47,
    "videos_pending": 12
  }
}
```

### GET /health

Simple health check for container orchestration.

**Response**: `200 OK` with body `{"healthy": true}`

### POST /crawler/trigger

Manually trigger a crawler run (if crawler enabled).

**Response**
```json
{
  "triggered": true,
  "videos_queued": 5
}
```

### GET /video/{path:path}/metadata

Retrieve existing metadata for a video without re-analyzing.

**Response**: Contents of the `.meta.json` sidecar, or `404` if not found.

## Analysis Pipeline

### Stage 1: Video Probe

Extract basic video metadata using ffprobe:
- Duration
- Resolution
- Codec
- Frame rate
- Creation timestamp (if available)

### Stage 2: Frame Extraction

Extract frames for analysis using a hybrid approach:

1. **Regular interval sampling**: Every N seconds (default 2.0)
2. **Scene change detection**: OpenCV frame differencing to catch transitions
3. **First/last frame**: Always include for context

Target: 30-60 frames for a typical 2-3 minute flight, capped at 100 frames maximum.

**FFmpeg extraction command**:
```bash
ffmpeg -i input.mp4 -vf "select='isnan(prev_selected_t)+gte(t-prev_selected_t\,2.0)',scale=1280:-1" \
       -vsync vfr -q:v 2 frames/frame_%04d.jpg
```

### Stage 3: Static Detection

Identify segments where the quad is stationary (pre-arm, post-land, DVR freeze).

**Algorithm**:
1. Compute frame-to-frame difference using structural similarity (SSIM) or mean absolute difference
2. Mark segments where difference < threshold for > 1 second
3. Classify by position:
   - First 30 seconds → likely "pre-arm" or "warmup"
   - Last 30 seconds → likely "post-land"
   - Mid-video → likely "DVR freeze" or "crash/pause"

**Thresholding considerations for FPV**:

FPV footage is characterized by constant motion—even hovering produces visible drift and vibration. True "static" in FPV footage means one of:

| Scenario | Visual Signature | Threshold Behavior |
|----------|------------------|-------------------|
| Pre-arm on ground | Completely frozen, possibly OSD blinking | Very low diff (< 0.01) |
| Post-land/disarm | Sudden freeze after motion | Very low diff (< 0.01) |
| DVR recording freeze | Frozen frame, OSD may update | Low diff, OSD region may differ |
| Goggle signal loss | Static/snow or frozen + artifacts | Varies; may need pattern detection |
| Actual hover | Subtle drift, vibration visible | Higher diff (0.02-0.05) |
| Slow cinematic | Smooth but continuous motion | Normal diff (> 0.05) |

**Recommended approach**:

```python
def detect_static_segments(frames: List[Frame], threshold: float = 0.02) -> List[Segment]:
    """
    Detect static segments using frame differencing.
    
    Args:
        frames: List of frames with timestamps
        threshold: SSIM difference threshold (0.02 = very static, 0.05 = slow motion)
    
    Returns:
        List of static segments with start/end times and classification
    """
    segments = []
    in_static = False
    static_start = 0
    
    for i in range(1, len(frames)):
        # Compare grayscale, downsampled frames for speed
        diff = compute_ssim_diff(frames[i-1].data, frames[i].data)
        
        if diff < threshold:
            if not in_static:
                in_static = True
                static_start = frames[i-1].timestamp
        else:
            if in_static:
                static_end = frames[i].timestamp
                if static_end - static_start > 1.0:  # Min 1 second
                    segments.append(Segment(
                        start=static_start,
                        end=static_end,
                        reason=classify_static(static_start, static_end, video_duration)
                    ))
                in_static = False
    
    return segments
```

**OSD handling**: The OSD (battery voltage, timer, RSSI, etc.) updates even when the quad is stationary. Options:
1. Mask the OSD region before comparison (requires knowing OSD position)
2. Use a slightly higher threshold to tolerate OSD flicker
3. Check if only specific screen regions are changing

For initial implementation, recommend option 2 (slightly higher threshold) as it's robust without configuration.

### Stage 4: Frame Analysis via LLM

For each sampled frame, query Ollama with a specialized prompt:

**System prompt**:
```
You are analyzing frames from FPV drone footage. Describe what you see concisely, focusing on:
- Environment (indoor/outdoor, terrain type, vegetation, structures)
- Flight characteristics (speed impression, proximity to objects, altitude)
- Maneuvers if identifiable (rolls, flips, split-s, gaps, proximity)
- Visual quality (clear, foggy, DVR artifacts, signal breakup)
- Notable features (interesting scenery, obstacles, other pilots)

Respond in JSON format:
{
  "description": "Brief description of the scene",
  "environment": ["outdoor", "forest"],
  "flight_style": "proximity",
  "interest_score": 7,
  "quality_issues": []
}
```

**Request to Ollama**:
```python
async def analyze_frame(frame_path: str, timestamp: float) -> FrameAnalysis:
    response = await ollama_client.generate(
        model=OLLAMA_MODEL,
        prompt="Analyze this FPV drone footage frame.",
        images=[frame_path],
        format="json",
        options={"temperature": 0.3}
    )
    return FrameAnalysis(
        timestamp=timestamp,
        **json.loads(response.response)
    )
```

### Stage 5: Aggregation and Summarization

Combine frame analyses into cohesive metadata:

1. **Tag extraction**: Collect all environment/style tags, keep those appearing in >20% of frames
2. **Highlight detection**: Find sequences of high interest_score frames (>7) lasting >5 seconds
3. **Summary generation**: Second LLM call with all frame descriptions to generate overall summary

**Summary prompt**:
```
Based on these frame-by-frame descriptions of an FPV drone flight, write a 2-3 sentence summary:

[Frame descriptions as bullet list]

Focus on: overall environment, flight style, and any notable moments.
```

### Stage 6: Output Generation

Write the `.meta.json` sidecar alongside the video file.

## Sidecar Schema

**File naming**: `{video_filename}.meta.json`
- Example: `flight_001.mp4` → `flight_001.mp4.meta.json`

**Schema version**: 1.0

```json
{
  "$schema": "https://example.com/fpv-video-meta-v1.schema.json",
  "schema_version": "1.0",
  "analyzed_at": "2025-01-15T14:30:00Z",
  "analyzer_version": "0.1.0",
  "ollama_model": "llava:13b",
  
  "source": {
    "filename": "flight_001.mp4",
    "duration_seconds": 142.5,
    "resolution": [1920, 1080],
    "framerate": 60.0,
    "codec": "h264",
    "file_size_bytes": 524288000,
    "creation_time": "2025-01-15T10:23:45Z",
    "source_type": "onboard"
  },
  
  "analysis": {
    "frames_analyzed": 45,
    "analysis_duration_seconds": 127.3
  },
  
  "tags": [
    "outdoor",
    "forest",
    "proximity",
    "freestyle"
  ],
  
  "summary": "Freestyle flight through a dense forest trail. Multiple proximity passes around tree trunks with occasional gaps. Flight ends with a controlled landing in a clearing.",
  
  "static_segments": [
    {
      "start": 0.0,
      "end": 4.2,
      "reason": "pre-arm",
      "confidence": 0.95
    },
    {
      "start": 138.1,
      "end": 142.5,
      "reason": "post-land",
      "confidence": 0.92
    }
  ],
  
  "highlights": [
    {
      "start": 24.5,
      "end": 38.2,
      "score": 9,
      "description": "Tight gap sequence through fallen tree branches",
      "tags": ["gap", "proximity"]
    },
    {
      "start": 67.0,
      "end": 82.1,
      "score": 8,
      "description": "Sustained proximity flying along narrow trail",
      "tags": ["proximity", "trail"]
    },
    {
      "start": 98.5,
      "end": 105.2,
      "score": 7,
      "description": "Power loop around large oak tree",
      "tags": ["freestyle", "power-loop"]
    }
  ],
  
  "frame_analysis": [
    {
      "timestamp": 5.0,
      "description": "Quad lifting off from grassy clearing, forest visible ahead",
      "environment": ["outdoor", "forest", "clearing"],
      "flight_style": "takeoff",
      "interest_score": 4,
      "quality_issues": []
    },
    {
      "timestamp": 7.0,
      "description": "Accelerating toward tree line, gaining altitude",
      "environment": ["outdoor", "forest"],
      "flight_style": "cruising",
      "interest_score": 5,
      "quality_issues": []
    }
  ],
  
  "quality": {
    "overall_score": 8,
    "issues": [],
    "dvr_artifacts_detected": false,
    "signal_loss_segments": []
  },
  
  "custom": {}
}
```

### Schema Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Schema version for forward compatibility |
| `analyzed_at` | ISO8601 | When analysis was performed |
| `source.source_type` | enum | `onboard`, `dvr`, `unknown` |
| `static_segments[].reason` | enum | `pre-arm`, `post-land`, `dvr-freeze`, `signal-loss`, `unknown` |
| `highlights[].score` | int | 1-10 interest rating |
| `quality.overall_score` | int | 1-10 video quality rating |
| `custom` | object | Reserved for user-defined fields |

## Crawler Behavior

When `CRAWLER_ENABLED=true`, a background task periodically scans `CRAWLER_ROOT` for videos to analyze.

### Scan Logic

```python
async def crawler_scan():
    """Find videos needing analysis."""
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv'}
    
    for root, dirs, files in os.walk(CRAWLER_ROOT):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for file in files:
            if Path(file).suffix.lower() not in video_extensions:
                continue
            
            video_path = Path(root) / file
            sidecar_path = video_path.with_suffix(video_path.suffix + '.meta.json')
            
            if not sidecar_path.exists():
                await queue_for_analysis(video_path)
```

### Processing Order

Videos are processed in order of:
1. File modification time (oldest first)
2. File size (smallest first, for faster initial results)

### Rate Limiting

To avoid overwhelming Ollama or the storage system:
- Maximum 1 concurrent analysis
- 30-second pause between analyses
- Skip files currently being written (check mtime stability)

## FileFlows Integration

Add a Function node after the move-to-date-folder action:

```javascript
/**
 * Trigger FPV video analysis
 * @output Analysis triggered successfully
 * @output Analysis skipped (not a video or already processed)
 */
function Script() {
    let videoPath = Variables.file.FullName;
    let ext = Variables.file.Extension.toLowerCase();
    
    // Only process video files
    if (!['.mp4', '.mov', '.avi', '.mkv'].includes(ext)) {
        Logger.ILog('Not a video file, skipping: ' + videoPath);
        return 2;
    }
    
    // Check if sidecar already exists
    let sidecarPath = videoPath + '.meta.json';
    if (Flow.FileExists(sidecarPath)) {
        Logger.ILog('Sidecar exists, skipping: ' + sidecarPath);
        return 2;
    }
    
    // Trigger analysis via HTTP
    let analyzerUrl = 'http://fpv-analyzer:8420/analyze';
    let process = Flow.Execute({
        command: 'curl',
        argumentList: [
            '-X', 'POST',
            '-H', 'Content-Type: application/json',
            '-d', JSON.stringify({ path: videoPath }),
            '--max-time', '600',
            analyzerUrl
        ]
    });
    
    if (process.exitCode !== 0) {
        Logger.WLog('Analysis request failed: ' + process.standardError);
        // Don't fail the flow, just log
        return 1;
    }
    
    Logger.ILog('Analysis triggered for: ' + videoPath);
    return 1;
}
```

**Alternative**: Use the crawler mode and skip FileFlows integration entirely. The crawler will pick up new videos automatically.

## Docker Compose

```yaml
version: '3.8'

services:
  fpv-analyzer:
    image: fpv-video-analyzer:latest
    build: .
    container_name: fpv-analyzer
    restart: unless-stopped
    ports:
      - "8420:8420"
    environment:
      - OLLAMA_HOST=http://ollama:11434
      - OLLAMA_MODEL=llava:13b
      - CRAWLER_ENABLED=true
      - CRAWLER_ROOT=/videos
      - CRAWLER_INTERVAL=1800
      - FRAME_SAMPLE_INTERVAL=2.0
      - STATIC_THRESHOLD=0.02
      - LOG_LEVEL=INFO
    volumes:
      - /path/to/videos:/videos
    depends_on:
      - ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8420/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  ollama_data:
```

## Project Structure

```
fpv-video-analyzer/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Environment config
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py        # HTTP endpoints
│   │   └── models.py        # Pydantic request/response models
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── pipeline.py      # Main analysis orchestrator
│   │   ├── frames.py        # Frame extraction
│   │   ├── static.py        # Static segment detection
│   │   ├── vision.py        # Ollama vision queries
│   │   └── aggregation.py   # Tag/highlight/summary generation
│   │
│   ├── crawler/
│   │   ├── __init__.py
│   │   └── scanner.py       # Directory crawler
│   │
│   └── models/
│       ├── __init__.py
│       └── schema.py        # Sidecar JSON schema models
│
├── tests/
│   ├── __init__.py
│   ├── test_static.py
│   ├── test_analysis.py
│   └── fixtures/
│       └── sample_frames/
│
└── scripts/
    ├── test_ollama.py       # Verify Ollama connectivity
    └── analyze_single.py    # CLI for single video analysis
```

## Implementation Phases

### Phase 1: Core Pipeline (MVP)

- [ ] Docker container with FastAPI
- [ ] `/analyze` endpoint (synchronous)
- [ ] Frame extraction via FFmpeg
- [ ] Basic Ollama integration
- [ ] JSON sidecar output
- [ ] Simple static detection (threshold only)

**Deliverable**: Analyze a single video via HTTP POST, get JSON sidecar.

### Phase 2: Crawler and Robustness

- [ ] Background crawler task
- [ ] Queue management
- [ ] Ollama connection retry/health checks
- [ ] Better static classification (pre-arm vs post-land vs DVR)
- [ ] `/status` endpoint

**Deliverable**: Drop videos in folder, get automatic analysis.

### Phase 3: Enhanced Analysis

- [ ] Highlight detection algorithm
- [ ] Summary generation (second LLM pass)
- [ ] DVR artifact detection
- [ ] Signal loss detection
- [ ] Quality scoring

**Deliverable**: Rich metadata with highlights and quality info.

### Phase 4: Integration and Polish

- [ ] FileFlows function node
- [ ] Optional XMP sidecar generation
- [ ] Optional static segment trimming
- [ ] Web UI for browsing analyzed videos (stretch goal)

**Deliverable**: Full integration with existing workflow.

## Open Questions

1. **OSD masking**: Should we attempt to detect and mask OSD regions for better static detection? This adds complexity but improves accuracy.

2. **Model choice**: Is llava:13b the best fit, or should we test llava:7b for speed vs. accuracy tradeoff?

3. **Highlight thresholds**: What interest_score threshold and minimum duration should define a "highlight"?

4. **Tagging taxonomy**: Should we define a controlled vocabulary for tags, or let the LLM generate freely?

5. **DVR vs onboard detection**: Can we reliably distinguish DVR recordings from onboard? (Resolution, OSD style, artifacts)

6. **Trimmed output**: If generating trimmed versions, should they replace originals or be separate files?

## References

- [video-analyzer](https://github.com/byjlw/video-analyzer) - Similar project for general video analysis
- [Ollama Vision Models](https://ollama.com/blog/vision-models) - LLaVA model documentation
- [ExifTool sidecar documentation](https://exiftool.org/metafiles.html) - XMP sidecar reference
- [Immich XMP support](https://docs.immich.app/features/xmp-sidecars/) - Photo manager sidecar implementation
