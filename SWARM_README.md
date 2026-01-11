# Multi-Agent Browser Swarm Mode 🚀

This document describes the Multi-Agent Browser Swarm feature, which enables parallel company research using multiple AI-controlled browser instances.

## Overview

The Browser Swarm allows running **5 concurrent browser agents** that research companies in parallel. Each agent has its own:
- Chromium browser instance
- Gemini AI agent
- Video stream for observation

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Next.js Webapp (port 3000) - Browser Swarm UI                     │
│  ┌──────────────────────────────────┐  ┌───────────────────────┐   │
│  │  BrowserGrid (2x3 grid)          │  │  ChatWindow           │   │
│  │  5 browser video streams         │  │  Orchestrator client  │   │
│  └──────────────────────────────────┘  └───────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  Orchestrator Service (port 8100)                                  │
│  - Parses natural language commands                                │
│  - Manages worker pool                                             │
│  - Aggregates results into markdown tables                         │
└────────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Worker 1        │  │ Worker 2        │  │ Worker 3-5...   │
│ Browser + Agent │  │ Browser + Agent │  │ Browser + Agent │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## Quick Start

### 1. Set Environment Variables

Ensure `.env` file has your Gemini API key:
```
GEMINI_API_KEY=your_api_key_here
```

### 2. Launch Swarm Mode

```bash
# Build and start all services
docker compose -f docker-compose.swarm.yml up --build

# Or run in detached mode
docker compose -f docker-compose.swarm.yml up --build -d
```

### 3. Access the UI

Open http://localhost:3000 in your browser.

### 4. Enable Swarm Mode Page

To use the swarm UI, rename the page files:
```bash
# Backup original
mv services/nextjs-webapp/src/app/page.tsx services/nextjs-webapp/src/app/page-single.tsx

# Enable swarm mode
mv services/nextjs-webapp/src/app/page-swarm.tsx services/nextjs-webapp/src/app/page.tsx
```

## Usage Examples

In the chat window, try these commands:

```
Look up 5 YC companies evaluation value
```

```
Research valuation for first 3 companies
```

```
Analyze 10 startups from YC W25
```

## Resource Requirements

| Workers | RAM Required | CPU Cores | Total Ports |
|---------|-------------|-----------|-------------|
| 5 (default) | ~15 GB | 10+ | 20 |

**Note:** Each browser worker requires approximately 2GB of shared memory (`shm_size`).

## Port Assignments

| Service | Base Port | Worker Ports |
|---------|-----------|--------------|
| Orchestrator | 8100 | - |
| Agent API | 8001 | 8001-8005 |
| Video Stream | 8766 | 8766-8770 |
| VNC | 6081 | 6081-6085 |
| MCP | 3011 | 3011-3015 |
| Webapp | 3000 | - |

## API Endpoints

### Orchestrator REST API

**Health Check:**
```bash
curl http://localhost:8100/health
```

**Get Status:**
```bash
curl http://localhost:8100/status
```

**List Workers:**
```bash
curl http://localhost:8100/workers
```

**List Companies:**
```bash
curl http://localhost:8100/companies?limit=10
```

**Execute Task:**
```bash
curl -X POST http://localhost:8100/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "Look up 5 YC companies evaluation value"}'
```

### WebSocket API

Connect to `ws://localhost:8100/ws` for real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:8100/ws')
ws.send(JSON.stringify({
  type: 'message',
  content: 'Look up 5 YC companies evaluation value'
}))
```

## File Structure

```
services/
├── orchestrator/           # Swarm orchestrator
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py             # FastAPI server
│   ├── models.py           # Pydantic models
│   ├── worker_pool.py      # Worker management
│   └── command_parser.py   # NLP command parsing
├── nextjs-webapp/
│   └── src/
│       ├── app/
│       │   ├── page.tsx         # Original single-agent page
│       │   └── page-swarm.tsx   # Swarm mode page
│       └── components/
│           ├── BrowserGrid.tsx  # Multi-browser grid
│           └── ChatWindow.tsx   # Updated with orchestrator support
├── playwright-browser/     # Browser container (5 instances)
└── python-agent/           # Agent container (5 instances)

docker-compose.swarm.yml    # Multi-worker configuration
```

## Troubleshooting

### Workers not connecting
```bash
# Check worker health
docker compose -f docker-compose.swarm.yml ps
docker compose -f docker-compose.swarm.yml logs worker-1
```

### Out of memory
Reduce worker count by editing `docker-compose.swarm.yml` and removing worker-4 and worker-5 services.

### Port conflicts
Check for existing services on the required ports:
```bash
lsof -i :8100 -i :8001 -i :8766 -i :6081
```

## Development Notes

- The orchestrator reads company data from `test_cases/competitor_analysis/data/companies.json`
- Workers communicate with the orchestrator via internal Docker network
- Video streams are MJPEG over WebSocket for low-latency observation
- Results are formatted as markdown tables in the chat
