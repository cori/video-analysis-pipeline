# FPV Video Analyzer

A containerized service for analyzing FPV drone footage using local LLMs (Ollama + LLaVA), generating structured metadata with tags, summaries, highlight detection, and static segment identification.

## Features

- **Automated Video Analysis**: Extract frames, detect static segments, identify highlights
- **AI-Powered Metadata**: Uses Ollama vision models to understand video content
- **JSON Sidecars**: Generates `.meta.json` files alongside videos for easy indexing
- **HTTP API**: RESTful API for integration with other tools
- **Optional Directory Crawler**: Automatically process new videos
- **Docker-First**: Runs entirely in containers, no host dependencies

## Quick Start

### Prerequisites

- Docker and Docker Compose
- At least 16GB RAM (for llava:13b model)
- NVIDIA GPU with CUDA support (recommended, but CPU works too)

### 1. Clone and Build

```bash
git clone <repository-url>
cd video-analysis-pipeline

# Build the container
docker-compose build
```

### 2. Pull the Ollama Model

```bash
# Start Ollama
docker-compose up -d ollama

# Pull the vision model (this will take a few minutes and ~8GB download)
docker exec -it ollama ollama pull llava:13b
```

### 3. Configure Video Path

Edit `docker-compose.yml` and update the volume mount:

```yaml
volumes:
  - /path/to/your/videos:/videos  # Change this to your video directory
```

### 4. Start the Service

```bash
docker-compose up -d

# Check logs
docker-compose logs -f fpv-analyzer
```

### 5. Test the API

```bash
# Health check
curl http://localhost:8420/health

# Check status
curl http://localhost:8420/status

# Analyze a video
curl -X POST http://localhost:8420/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/videos/your-video.mp4",
    "force": false
  }'
```

## Usage

### API Endpoints

#### POST `/analyze`

Analyze a single video file.

**Request:**
```json
{
  "path": "/videos/flight_001.mp4",
  "force": false,
  "options": {
    "generate_xmp": false,
    "trim_static": false
  }
}
```

**Response:**
```json
{
  "status": "complete",
  "path": "/videos/flight_001.mp4",
  "sidecar": "/videos/flight_001.mp4.meta.json",
  "duration_seconds": 142.5,
  "tags": ["outdoor", "forest", "proximity"],
  "highlights_count": 3,
  "static_segments_count": 2
}
```

#### GET `/status`

Get service status and Ollama connectivity.

#### GET `/health`

Simple health check (returns `{"healthy": true}`).

#### GET `/video/{path}/metadata`

Retrieve existing metadata without re-analyzing.

### Command-Line Scripts

#### Test Ollama Connection

```bash
python scripts/test_ollama.py
```

This verifies:
- Ollama is accessible
- Required model is available
- API is responding

#### Analyze Single Video

```bash
python scripts/analyze_single.py /path/to/video.mp4

# Force re-analysis
python scripts/analyze_single.py --force /path/to/video.mp4
```

### Environment Variables

Configure via `.env` file or docker-compose environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llava:13b` | Vision model to use |
| `CRAWLER_ENABLED` | `false` | Enable background crawler |
| `CRAWLER_ROOT` | `/videos` | Root directory to scan |
| `CRAWLER_INTERVAL` | `3600` | Seconds between scans |
| `FRAME_SAMPLE_INTERVAL` | `2.0` | Seconds between frames |
| `STATIC_THRESHOLD` | `0.02` | Static detection sensitivity |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## How It Works

### Analysis Pipeline

1. **Video Probe**: Extract metadata (duration, resolution, codec) using ffprobe
2. **Frame Extraction**: Sample frames at regular intervals using ffmpeg/OpenCV
3. **Static Detection**: Identify stationary segments (pre-arm, post-land, DVR freezes)
4. **Frame Analysis**: Send frames to Ollama vision model for scene understanding
5. **Aggregation**: Combine frame analyses into tags, highlights, and quality scores
6. **Summary Generation**: Create overall summary using LLM
7. **Sidecar Output**: Write JSON metadata file

### Metadata Schema

Each video gets a `.meta.json` sidecar with:

```json
{
  "schema_version": "1.0",
  "analyzed_at": "2025-01-15T14:30:00Z",
  "source": {
    "filename": "flight_001.mp4",
    "duration_seconds": 142.5,
    "resolution": [1920, 1080],
    "framerate": 60.0
  },
  "tags": ["outdoor", "forest", "proximity"],
  "summary": "Freestyle flight through forest...",
  "static_segments": [...],
  "highlights": [...],
  "frame_analysis": [...],
  "quality": {...}
}
```

See [fpv-video-analyzer-plan.md](./fpv-video-analyzer-plan.md) for complete schema documentation.

## Development

### Project Structure

```
video-analysis-pipeline/
├── src/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Configuration
│   ├── api/
│   │   ├── routes.py        # HTTP endpoints
│   │   └── models.py        # Request/response models
│   ├── analysis/
│   │   ├── pipeline.py      # Main orchestrator
│   │   ├── frames.py        # Frame extraction
│   │   ├── static.py        # Static detection
│   │   ├── vision.py        # Ollama integration
│   │   └── aggregation.py   # Tag/highlight generation
│   └── models/
│       └── schema.py        # Sidecar JSON schema
├── scripts/
│   ├── test_ollama.py       # Test Ollama connectivity
│   └── analyze_single.py    # CLI analysis tool
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### Running Locally (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Make sure Ollama is running locally
ollama serve

# Pull model
ollama pull llava:13b

# Set environment
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=llava:13b

# Run server
python -m uvicorn src.main:app --reload --port 8420

# Or analyze single video
python scripts/analyze_single.py /path/to/video.mp4
```

### Running Tests

```bash
# TODO: Add pytest tests
pytest tests/
```

## Integration Examples

### FileFlows Integration

Add this Function node after moving videos:

```javascript
function Script() {
    let videoPath = Variables.file.FullName;

    if (!['.mp4', '.mov', '.avi'].includes(Variables.file.Extension.toLowerCase())) {
        return 2; // Skip non-videos
    }

    let response = Flow.Execute({
        command: 'curl',
        argumentList: [
            '-X', 'POST',
            '-H', 'Content-Type: application/json',
            '-d', JSON.stringify({ path: videoPath }),
            'http://fpv-analyzer:8420/analyze'
        ]
    });

    return response.exitCode === 0 ? 1 : 2;
}
```

### Python Script Integration

```python
import httpx

async def analyze_video(video_path: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8420/analyze",
            json={"path": video_path}
        )
        return response.json()

# Use it
result = await analyze_video("/videos/flight.mp4")
print(f"Found {result['highlights_count']} highlights!")
```

## Troubleshooting

### Ollama Connection Failed

```bash
# Check if Ollama is running
docker-compose ps

# Check Ollama logs
docker-compose logs ollama

# Test connectivity
curl http://localhost:11434/api/tags
```

### Model Not Found

```bash
# Pull the model
docker exec -it ollama ollama pull llava:13b

# List available models
docker exec -it ollama ollama list
```

### Out of Memory

- Reduce `MAX_FRAMES_PER_VIDEO` in environment (default: 100)
- Use a smaller model: `llava:7b` instead of `llava:13b`
- Increase Docker memory limit in Docker Desktop settings

### Analysis Too Slow

- Use GPU acceleration (uncomment GPU section in docker-compose.yml)
- Reduce `FRAME_SAMPLE_INTERVAL` (extract fewer frames)
- Use smaller model (`llava:7b`)

## Roadmap

### Phase 1: Core Pipeline (MVP) ✅

- [x] Docker container with FastAPI
- [x] `/analyze` endpoint
- [x] Frame extraction via FFmpeg
- [x] Ollama integration
- [x] JSON sidecar output
- [x] Static detection

### Phase 2: Crawler and Robustness

- [ ] Background crawler task
- [ ] Queue management
- [ ] Enhanced static classification
- [ ] Retry logic for Ollama failures

### Phase 3: Enhanced Analysis

- [ ] Improved highlight detection
- [ ] DVR artifact detection
- [ ] Signal loss detection
- [ ] Quality scoring refinements

### Phase 4: Integration and Polish

- [ ] FileFlows example
- [ ] XMP sidecar generation
- [ ] Static segment trimming
- [ ] Web UI for browsing analyzed videos

## License

MIT

## Contributing

Contributions welcome! Please see [fpv-video-analyzer-plan.md](./fpv-video-analyzer-plan.md) for architecture details.

## Credits

Inspired by:
- [video-analyzer](https://github.com/byjlw/video-analyzer)
- [Ollama Vision Models](https://ollama.com/blog/vision-models)
