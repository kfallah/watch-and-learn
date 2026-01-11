# Single-Agent vs Multi-Agent Swarm Architecture Changes

This document captures the key differences between the original single-agent architecture (commit 18b5956) and the multi-agent swarm implementation.

## Files Modified for Swarm Mode

### 1. `services/nextjs-webapp/src/app/page.tsx`

**Original (Single-Agent):**
- Simple single-browser view with Observe/Control toggle
- Uses `VideoViewer` + `VNCViewer` components
- `isRecording` state for recording mode
- Connects to single agent at `ws://localhost:8000/ws`

**Swarm Changes:**
- Multi-browser grid view with `BrowserGrid` component
- `agentMode` state: 'single' | 'multi'
- Orchestrator connection at `ws://localhost:8100/ws`
- Worker status tracking and display

### 2. `services/nextjs-webapp/src/components/ChatWindow.tsx`

**Original (Single-Agent):**
```tsx
interface ChatWindowProps {
  isRecording?: boolean
}
// Always connects to ws://localhost:8000/ws
const wsUrl = `ws://${window.location.hostname}:8000/ws`
```

**Swarm Changes:**
```tsx
interface ChatWindowProps {
  isRecording?: boolean
  useOrchestrator?: boolean  // NEW
}
// Conditional connection
const wsUrl = useOrchestrator
  ? `ws://${window.location.hostname}:8100/ws`  // orchestrator
  : `ws://${window.location.hostname}:8001/ws`  // worker-1
```

Additional swarm additions:
- `renderMarkdownTable()` function for valuation table display
- `isMarkdown` property in Message interface
- Status messages display in orchestrator mode

### 3. `services/python-agent/main.py`

**Original (Single-Agent):**
- Only `/ws`, `/health`, `/recording/*` endpoints

**Swarm Addition:**
```python
@app.post("/execute")
async def execute_task(request: dict):
    """Execute a browser automation task from the orchestrator."""
    prompt = request.get("prompt", "")
    agent = await get_or_create_recording_agent()
    response = await agent.process_message(prompt)
    return {"response": response, "status": "success"}
```

### 4. `docker-compose.swarm.yml` (New File)

Created for multi-agent swarm with:
- Orchestrator service (port 8100)
- Multiple browser-worker pairs (browser-N + worker-N)
- Port mapping: 8001-800N for workers, 8766-876N for video

### 5. `services/orchestrator/` (New Directory)

New services for swarm orchestration:
- `main.py` - FastAPI WebSocket server
- `command_parser.py` - Gemini-based command parsing
- `worker_pool.py` - Worker management and task distribution
- `models.py` - Pydantic models for workers/tasks

## Port Mapping Reference

| Component | Single-Agent | Swarm Mode |
|-----------|-------------|------------|
| Webapp | 3000 | 3000 |
| Python Agent | 8000 | 8001-800N (workers) |
| Orchestrator | N/A | 8100 |
| VNC | 6080 | 6081-608N |
| Video | 8765 | 8766-876N |
| MCP | 3001 | 3011-301N |

## How to Switch Between Modes

### Run Single-Agent Mode:
```bash
docker-compose up --build
# Uses: docker-compose.yml
# Connects: webapp → python-agent → playwright-browser
```

### Run Swarm Mode:
```bash
docker-compose -f docker-compose.swarm.yml up --build
# Uses: docker-compose.swarm.yml
# Connects: webapp → orchestrator → workers → browsers
```

## Restoring Single-Agent Functionality

To restore original single-agent behavior:
1. Use original `page.tsx` (with VideoViewer/VNCViewer)
2. Use original `ChatWindow.tsx` (no useOrchestrator prop)
3. Run `docker-compose.yml` instead of `docker-compose.swarm.yml`
