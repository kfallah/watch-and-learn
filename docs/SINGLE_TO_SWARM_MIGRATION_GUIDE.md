# Single-Agent to Multi-Agent Swarm Migration Guide

> **Technical Documentation for Watch-and-Learn Browser Automation System**
>
> This comprehensive guide details the architectural evolution from a single-agent browser automation system to a parallel multi-agent swarm capable of orchestrating N concurrent browser instances.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
   - [Single-Agent Architecture](#single-agent-architecture)
   - [Multi-Agent Swarm Architecture](#multi-agent-swarm-architecture)
3. [Component Deep Dive](#component-deep-dive)
   - [Browser Container](#browser-container-playwright-browser)
   - [Python Agent Worker](#python-agent-worker)
   - [Orchestrator Service](#orchestrator-service)
   - [Frontend Webapp](#frontend-webapp)
4. [Data Flow Analysis](#data-flow-analysis)
5. [Service Discovery System](#service-discovery-system)
6. [Docker Configuration](#docker-configuration)
7. [Port Mapping Reference](#port-mapping-reference)
8. [Code Changes by File](#code-changes-by-file)
9. [Migration Checklist](#migration-checklist)
10. [Troubleshooting Guide](#troubleshooting-guide)

---

## Executive Summary

| Dimension | Single-Agent | Multi-Agent Swarm |
|-----------|-------------|-------------------|
| **Browser Instances** | 1 | N (configurable, default 2-5) |
| **AI Agents** | 1 | N parallel workers |
| **Orchestrator** | None | FastAPI service (port 8100) |
| **Command Parsing** | Direct Gemini API | LangChain + Gemini structured output |
| **Task Distribution** | Sequential | Parallel via worker pool |
| **Frontend** | Single browser viewer | Multi-browser grid |
| **Service Discovery** | Hardcoded ports | Dynamic `/services` endpoint |

### Key Benefits of Swarm Architecture

1. **Parallel Execution** — Research N companies simultaneously instead of sequentially
2. **Fault Tolerance** — Individual worker failures don't crash the entire system
3. **Scalability** — Add/remove workers by modifying docker-compose
4. **Observability** — Real-time video streams from all browser instances
5. **Aggregation** — Results synthesized into unified markdown tables

---

## Architecture Overview

### Single-Agent Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        docker-compose.yml                             │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│   │ Next.js Webapp  │───▶│  Python Agent   │───▶│  Playwright     │  │
│   │   (port 3000)   │    │   (port 8000)   │    │  Browser        │  │
│   │                 │    │                 │    │  (port 3001)    │  │
│   │ • VideoViewer   │    │ • BrowserAgent  │    │  • MCP Server   │  │
│   │ • VNCViewer     │    │ • Gemini API    │    │  • Chromium     │  │
│   │ • ChatWindow    │    │ • MCP Client    │    │  • VNC/Video    │  │
│   └─────────────────┘    └─────────────────┘    └─────────────────┘  │
│                                                                       │
│   Data Flow: User → WebSocket → Agent → MCP Tools → Browser          │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Multi-Agent Swarm Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                        docker-compose.swarm.yml                                 │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌─────────────────────────────────────────────────────────────────────────┐  │
│   │  Next.js Webapp (port 3000)                                              │  │
│   │  ┌──────────────────────────────┐  ┌──────────────────────────────────┐ │  │
│   │  │  BrowserGrid Component       │  │  ChatWindow Component            │ │  │
│   │  │  • N video tiles             │  │  • Orchestrator WebSocket        │ │  │
│   │  │  • Dynamic URL discovery     │  │  • Single/Swarm mode toggle      │ │  │
│   │  └──────────────────────────────┘  └──────────────────────────────────┘ │  │
│   └─────────────────────────────────────────────────────────────────────────┘  │
│                                        │                                        │
│                                        ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────────┐  │
│   │  Orchestrator Service (port 8100)                                        │  │
│   │  • CommandParser: Natural language → SwarmCommand                        │  │
│   │  • WorkerPool: Task distribution & health monitoring                     │  │
│   │  • ResultAggregator: Synthesize into markdown tables                     │  │
│   │  • ServiceDiscovery: GET /services endpoint                              │  │
│   └─────────────────────────────────────────────────────────────────────────┘  │
│                                        │                                        │
│            ┌───────────────────────────┼───────────────────────────┐           │
│            ▼                           ▼                           ▼           │
│   ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐   │
│   │   Worker-1      │        │   Worker-2      │        │   Worker-N      │   │
│   │   (port 8001)   │        │   (port 8002)   │        │   (port 800N)   │   │
│   │ ┌─────────────┐ │        │ ┌─────────────┐ │        │ ┌─────────────┐ │   │
│   │ │BrowserAgent │ │        │ │BrowserAgent │ │        │ │BrowserAgent │ │   │
│   │ └──────┬──────┘ │        │ └──────┬──────┘ │        │ └──────┬──────┘ │   │
│   │        │        │        │        │        │        │        │        │   │
│   │        ▼        │        │        ▼        │        │        ▼        │   │
│   │ ┌─────────────┐ │        │ ┌─────────────┐ │        │ ┌─────────────┐ │   │
│   │ │ Browser-1   │ │        │ │ Browser-2   │ │        │ │ Browser-N   │ │   │
│   │ │ MCP:3011    │ │        │ │ MCP:3012    │ │        │ │ MCP:301N    │ │   │
│   │ │ Video:8766  │ │        │ │ Video:8767  │ │        │ │ Video:876N  │ │   │
│   │ │ VNC:6081    │ │        │ │ VNC:6082    │ │        │ │ VNC:608N    │ │   │
│   │ └─────────────┘ │        │ └─────────────┘ │        │ └─────────────┘ │   │
│   └─────────────────┘        └─────────────────┘        └─────────────────┘   │
│                                                                                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Deep Dive

### Browser Container (playwright-browser)

The browser container provides a headless Chromium environment with multiple access methods.

**Services Running Inside Container:**
| Service | Internal Port | Purpose |
|---------|---------------|---------|
| Xvfb | :99 | Virtual framebuffer display |
| x11vnc | 5900 | VNC server for remote control |
| websockify | 6080 | WebSocket proxy for noVNC |
| video_server.py | 8765 | MJPEG video stream over WebSocket |
| Playwright MCP | 3001 | Model Context Protocol server (22 tools) |
| Chromium | 9222 | Remote debugging protocol |

**Dockerfile Key Points:**
```dockerfile
FROM mcr.microsoft.com/playwright:v1.52.0-noble
# Installs: chromium, ffmpeg, x11vnc, websockify, supervisor
# Entrypoint: starts all services in sequence
```

**MCP Tools Available (22 total):**
- Navigation: `browser_navigate`, `browser_go_back`, `browser_go_forward`
- Interaction: `browser_click`, `browser_type`, `browser_scroll`
- Screenshots: `browser_take_screenshot`, `browser_snapshot`
- Tabs: `browser_tab_new`, `browser_tab_select`, `browser_tab_close`
- And more...

---

### Python Agent Worker

Each worker is an independent instance of the `BrowserAgent` class.

**Key Files:**
```
services/python-agent/
├── main.py           # FastAPI app with /ws, /health, /execute endpoints
├── agent.py          # BrowserAgent class - agentic loop with Gemini
├── mcp_client.py     # MCP connection management
├── prompts.py        # System prompts for Gemini
├── models.py         # Pydantic models (AgentResponse, ToolCall)
└── config.py         # Environment configuration
```

**Agentic Loop (agent.py):**
```python
async def process_message(self, user_message: str) -> str:
    """30-iteration agentic loop with tool execution."""
    for iteration in range(MAX_ITERATIONS):
        # 1. Send message + screenshot to Gemini
        response = await self._get_llm_response(user_message)

        # 2. Parse structured response
        parsed = self._parse_response(response)

        # 3. If tool_call, execute via MCP
        if parsed.tool_call:
            result = await self.mcp_client.execute_tool(
                parsed.tool_call.tool_name,
                parsed.tool_call.arguments
            )
            # Add result to context and continue loop

        # 4. If user_message, return to frontend
        if parsed.user_message:
            return parsed.user_message
```

**Response Schema:**
```python
class AgentResponse(BaseModel):
    thinking: Optional[str]       # Internal reasoning (logged)
    user_message: Optional[str]   # Displayed to user
    tool_call: Optional[ToolCall] # MCP tool to execute

class ToolCall(BaseModel):
    tool_name: str
    arguments: dict
```

---

### Orchestrator Service

The orchestrator is the **new component** added for swarm mode.

**Key Files:**
```
services/orchestrator/
├── main.py           # FastAPI app with /ws, /services, /execute
├── command_parser.py # LangChain + Gemini for NLP parsing
├── worker_pool.py    # Worker management and parallel execution
└── models.py         # SwarmCommand, TaskResult, WorkerStatus
```

**Command Parser (LangChain Integration):**
```python
class CommandParser:
    """Parses natural language into structured SwarmCommand."""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            temperature=0,
        )

    def parse(self, command: str) -> ParsedCommand:
        # Uses structured output schema
        return ParsedCommand(
            action="lookup",      # lookup|analyze|compare|track
            query_type="valuation", # valuation|overview|funding
            target_count=5,
            companies=["Company A", "Company B", ...],
        )
```

**Worker Pool (Parallel Execution):**
```python
class WorkerPool:
    """Manages N workers for parallel task execution."""

    async def execute_parallel_tasks(
        self,
        tasks: list[tuple[str, str]]  # [(company_name, prompt), ...]
    ) -> list[TaskResult]:
        # Uses asyncio.gather for parallel HTTP calls
        results = await asyncio.gather(*[
            self._execute_on_worker(worker_id, prompt)
            for worker_id, (name, prompt) in enumerate(tasks)
        ])
        return results
```

**Service Discovery Endpoint:**
```python
@app.get("/services")
async def get_services():
    """Returns all service URLs for frontend discovery."""
    return {
        "orchestrator": {
            "ws": "ws://localhost:8100/ws",
            "http": "http://localhost:8100",
        },
        "workers": [
            {"id": 1, "ws": "ws://localhost:8001/ws", "http": "http://localhost:8001"},
            {"id": 2, "ws": "ws://localhost:8002/ws", "http": "http://localhost:8002"},
        ],
        "browsers": [
            {"id": 1, "video_ws": "ws://localhost:8766", "vnc_ws": "ws://localhost:6081"},
            {"id": 2, "video_ws": "ws://localhost:8767", "vnc_ws": "ws://localhost:6082"},
        ],
        "worker_count": 2,
    }
```

---

### Frontend Webapp

The Next.js frontend adapts its UI based on single vs. swarm mode.

**Key Components:**

| Component | Single-Agent | Swarm Mode |
|-----------|-------------|------------|
| `page.tsx` | `VideoViewer` + `VNCViewer` | `BrowserGrid` with N tiles |
| `ChatWindow.tsx` | Connect to worker-1:8001 | Connect to orchestrator:8100 |
| `BrowserGrid.tsx` | N/A | Grid of MJPEG video streams |
| `ServiceContext.tsx` | N/A | Service discovery provider |

**Service Context Pattern:**
```typescript
// contexts/ServiceContext.tsx
export function ServiceProvider({ children }) {
  const [services, setServices] = useState(null)

  useEffect(() => {
    fetch('http://localhost:8100/services')
      .then(res => res.json())
      .then(setServices)
  }, [])

  return (
    <ServiceContext.Provider value={services}>
      {children}
    </ServiceContext.Provider>
  )
}

// Components use hooks instead of hardcoded ports
const videoUrls = useVideoStreamUrls() // ['ws://localhost:8766', ...]
const workers = useWorkerUrls()        // [{ws: '...', http: '...'}, ...]
```

---

## Data Flow Analysis

### Single-Agent Mode

```
1. User types message in ChatWindow
2. WebSocket sends to ws://localhost:8001/ws
3. Worker-1 receives, calls BrowserAgent.process_message()
4. Agent sends to Gemini API with screenshot
5. Gemini returns AgentResponse (thinking + tool_call or user_message)
6. If tool_call: Execute via MCP, get result, add to context, loop
7. If user_message: Send back to ChatWindow via WebSocket
```

### Swarm Mode

```
1. User types command: "Look up 5 YC companies valuation"
2. WebSocket sends to ws://localhost:8100/ws (orchestrator)
3. CommandParser extracts: action=lookup, count=5, query=valuation
4. WorkerPool selects 5 companies from companies.json
5. Parallel HTTP POST to /execute on workers 1-5
6. Each worker runs independent agentic loop
7. Results collected by orchestrator
8. Gemini synthesizes results into markdown table
9. Table sent back to ChatWindow
```

---

## Service Discovery System

### Problem: Hardcoded Ports

Original architecture hardcoded WebSocket URLs:
```typescript
// ChatWindow.tsx (OLD)
const wsUrl = `ws://${window.location.hostname}:8000/ws`

// BrowserGrid.tsx (OLD)
const baseUrl = 'ws://localhost:8765'
```

This breaks when Docker maps internal port 8765 to external 8766.

### Solution: Dynamic Discovery

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend loads                                                  │
│       │                                                          │
│       ▼                                                          │
│  ServiceContext fetches GET /services from orchestrator          │
│       │                                                          │
│       ▼                                                          │
│  {                                                               │
│    "workers": [                                                  │
│      {"id": 1, "ws": "ws://localhost:8001/ws", ...},            │
│      {"id": 2, "ws": "ws://localhost:8002/ws", ...}             │
│    ],                                                            │
│    "browsers": [                                                 │
│      {"id": 1, "video_ws": "ws://localhost:8766", ...},         │
│      {"id": 2, "video_ws": "ws://localhost:8767", ...}          │
│    ]                                                             │
│  }                                                               │
│       │                                                          │
│       ▼                                                          │
│  Components use useWorkerUrls(), useVideoStreamUrls() hooks      │
└─────────────────────────────────────────────────────────────────┘
```

### Configuration via Environment Variables

```python
# orchestrator/main.py
ORCHESTRATOR_WS_PORT = int(os.getenv("ORCHESTRATOR_WS_PORT", "8100"))
WORKER_BASE_PORT = int(os.getenv("WORKER_BASE_PORT", "8001"))
VIDEO_STREAM_BASE_PORT = int(os.getenv("VIDEO_STREAM_BASE_PORT", "8766"))
VNC_BASE_PORT = int(os.getenv("VNC_BASE_PORT", "6081"))
```

---

## Docker Configuration

### docker-compose.yml (Single-Agent)

```yaml
services:
  playwright-browser:
    build: ./services/playwright-browser
    ports:
      - "6080:6080"   # VNC WebSocket
      - "8765:8765"   # Video stream
      - "3001:3001"   # MCP server
    shm_size: '2gb'

  python-agent:
    build: ./services/python-agent
    ports:
      - "8000:8000"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - MCP_SERVER_URL=http://playwright-browser:3001
    depends_on:
      - playwright-browser

  nextjs-webapp:
    build: ./services/nextjs-webapp
    ports:
      - "3000:3000"
    depends_on:
      - python-agent
```

### docker-compose.swarm.yml (Multi-Agent)

```yaml
services:
  # Browser instances (one per worker)
  browser-1:
    build: ./services/playwright-browser
    ports:
      - "6081:6080"    # VNC
      - "8766:8765"    # Video
      - "3011:3001"    # MCP
    networks:
      - swarm-network

  browser-2:
    build: ./services/playwright-browser
    ports:
      - "6082:6080"
      - "8767:8765"
      - "3012:3001"
    networks:
      - swarm-network

  # Worker instances (one per browser)
  worker-1:
    build: ./services/python-agent
    ports:
      - "8001:8000"
    environment:
      - MCP_SERVER_URL=http://browser-1:3001
      - WORKER_ID=1
    depends_on:
      browser-1:
        condition: service_healthy
    networks:
      - swarm-network

  worker-2:
    build: ./services/python-agent
    ports:
      - "8002:8000"
    environment:
      - MCP_SERVER_URL=http://browser-2:3001
      - WORKER_ID=2
    depends_on:
      browser-2:
        condition: service_healthy
    networks:
      - swarm-network

  # Orchestrator (new for swarm)
  orchestrator:
    build: ./services/orchestrator
    ports:
      - "8100:8100"
    environment:
      - MAX_WORKERS=2
      - WORKER_BASE_PORT=8001
    depends_on:
      - worker-1
      - worker-2
    networks:
      - swarm-network

  # Frontend
  nextjs-webapp:
    build: ./services/nextjs-webapp
    ports:
      - "3000:3000"
    depends_on:
      - orchestrator
    networks:
      - swarm-network

networks:
  swarm-network:
    driver: bridge
```

---

## Port Mapping Reference

### Single-Agent Mode

| Service | Internal | External | Protocol |
|---------|----------|----------|----------|
| Webapp | 3000 | 3000 | HTTP |
| Agent | 8000 | 8000 | HTTP/WS |
| MCP Server | 3001 | 3001 | HTTP SSE |
| VNC | 6080 | 6080 | WebSocket |
| Video Stream | 8765 | 8765 | WebSocket |

### Swarm Mode (N=2 workers)

| Service | Internal | External | Protocol |
|---------|----------|----------|----------|
| Webapp | 3000 | 3000 | HTTP |
| Orchestrator | 8100 | 8100 | HTTP/WS |
| Worker-1 | 8000 | 8001 | HTTP/WS |
| Worker-2 | 8000 | 8002 | HTTP/WS |
| Browser-1 MCP | 3001 | 3011 | HTTP SSE |
| Browser-2 MCP | 3001 | 3012 | HTTP SSE |
| Browser-1 VNC | 6080 | 6081 | WebSocket |
| Browser-2 VNC | 6080 | 6082 | WebSocket |
| Browser-1 Video | 8765 | 8766 | WebSocket |
| Browser-2 Video | 8765 | 8767 | WebSocket |

### Port Formula (for N workers)

```
Worker-N:      8000 + N
Browser-N MCP: 3010 + N
Browser-N VNC: 6080 + N
Browser-N Video: 8765 + N
```

---

## Code Changes by File

### New Files for Swarm

| File | Purpose |
|------|---------|
| `services/orchestrator/main.py` | FastAPI orchestrator with /ws, /services |
| `services/orchestrator/command_parser.py` | LangChain NLP command parsing |
| `services/orchestrator/worker_pool.py` | Parallel task distribution |
| `services/orchestrator/models.py` | Pydantic models for swarm |
| `services/nextjs-webapp/src/components/BrowserGrid.tsx` | Multi-video grid |
| `services/nextjs-webapp/src/contexts/ServiceContext.tsx` | Service discovery |
| `services/nextjs-webapp/src/app/providers.tsx` | Context provider wrapper |
| `docker-compose.swarm.yml` | Multi-service Docker config |

### Modified Files

| File | Changes |
|------|---------|
| `services/nextjs-webapp/src/app/page.tsx` | Added swarm view toggle, BrowserGrid |
| `services/nextjs-webapp/src/components/ChatWindow.tsx` | Added orchestrator connection, useServices hook |
| `services/nextjs-webapp/src/app/layout.tsx` | Wrapped with Providers |
| `services/python-agent/main.py` | Added `/execute` endpoint for orchestrator |

### Unchanged Core Files

| File | Reason |
|------|--------|
| `services/python-agent/agent.py` | BrowserAgent loop unchanged |
| `services/python-agent/mcp_client.py` | MCP connection unchanged |
| `services/playwright-browser/*` | Browser container unchanged |

---

## Migration Checklist

### Phase 1: Infrastructure

- [ ] Create `services/orchestrator/` directory
- [ ] Implement `main.py` with FastAPI endpoints
- [ ] Implement `worker_pool.py` for parallel execution
- [ ] Implement `command_parser.py` with LangChain
- [ ] Create `docker-compose.swarm.yml`

### Phase 2: Frontend Adaptation

- [ ] Create `ServiceContext.tsx` for service discovery
- [ ] Create `providers.tsx` wrapper component
- [ ] Update `layout.tsx` to use providers
- [ ] Create `BrowserGrid.tsx` for multi-video display
- [ ] Update `ChatWindow.tsx` for orchestrator mode
- [ ] Update `page.tsx` with swarm view toggle

### Phase 3: Backend Enhancements

- [ ] Add `/execute` endpoint to python-agent
- [ ] Add `/services` endpoint to orchestrator
- [ ] Configure environment variables for ports

### Phase 4: Testing

- [ ] Test single-agent mode still works
- [ ] Test swarm mode with 2 workers
- [ ] Test service discovery returns correct URLs
- [ ] Test parallel task execution
- [ ] Test result aggregation

---

## Troubleshooting Guide

### Workers show "unhealthy" status

**Cause:** Health check fails because optional services (MongoDB, Voyage AI) are not configured.

**Solution:** The workers are still functional for browser automation. The health check can be made more lenient:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

### WebSocket connection to wrong port

**Cause:** Frontend has hardcoded ports that don't match Docker mappings.

**Solution:** Use service discovery:
```typescript
const { services } = useServices()
const wsUrl = services?.workers[0]?.ws || 'ws://localhost:8001/ws'
```

### "Cannot find module 'react'" TypeScript errors

**Cause:** VS Code TypeScript server doesn't have access to node_modules inside Docker.

**Solution:** These are editor-only errors. The build succeeds inside Docker container where dependencies are installed.

### Orchestrator can't reach workers

**Cause:** Workers use internal Docker network hostnames.

**Solution:** Ensure services are on same Docker network:
```yaml
networks:
  - swarm-network
```

And use internal hostnames: `http://worker-1:8000` not `http://localhost:8001`

### Video streams not connecting

**Cause:** Port mismatch between internal (8765) and external (8766+).

**Solution:** Check `/services` endpoint returns correct external ports, and ensure BrowserGrid uses the discovered URLs.

---

## Resource Requirements

| Configuration | RAM | CPU Cores | Disk |
|---------------|-----|-----------|------|
| Single-Agent | ~4 GB | 4 | 10 GB |
| 2 Workers | ~8 GB | 6 | 15 GB |
| 5 Workers | ~15 GB | 10+ | 25 GB |

**Note:** Each browser instance requires ~2GB shared memory (`shm_size: '2gb'`).

---

## Future Enhancements

1. **Dynamic Worker Scaling** — Add/remove workers based on load
2. **Worker Health Dashboard** — Real-time status monitoring UI
3. **Result Caching** — Cache research results to avoid redundant lookups
4. **Priority Queue** — Prioritize certain tasks over others
5. **Kubernetes Deployment** — Scale beyond single-host Docker

---

*Document Version: 1.0.0*
*Last Updated: January 2026*
*Authors: Watch-and-Learn Development Team*
