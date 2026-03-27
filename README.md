# Watch and Learn

A Docker Compose application that lets you watch and interact with a browser controlled by an AI agent. Features hybrid control where you can both chat with the agent and directly interact with the browser.

## Architecture

### System Overview

```
                          ┌─────────────────────────────────────────────┐
                          │              User Browser (:3000)           │
                          │                                             │
                          │   ┌─ Observe tab ─┐  ┌─── Chat panel ───┐  │
                          │   │ MJPEG stream   │  │ WebSocket msgs   │  │
                          │   └────────────────┘  └──────────────────┘  │
                          │   ┌─ Control tab ──┐                        │
                          │   │ noVNC (direct) │                        │
                          │   └────────────────┘                        │
                          └──────────┬──────────────────┬───────────────┘
                                     │                  │
                       VNC (ws:6080) │                  │ WebSocket (:8000/ws)
                      MJPEG (ws:8765)│                  │
                                     ▼                  ▼
┌──────────────────────────────────────────┐  ┌──────────────────────────────────────┐
│         playwright-browser               │  │           python-agent               │
│                                          │  │                                      │
│  Xvfb (virtual display :99)             │  │  FastAPI server (:8000)              │
│  Chromium (CDP on :9222)                │  │  BrowserAgent (agentic loop)         │
│  x11vnc → websockify (:6080)           │  │  MCP Client ──── SSE (:3001) ───────►│
│  FFmpeg → video_server.py               │  │  RAG Retriever                       │
│    ├─ MJPEG stream    (:8765)           │  │                                      │
│    └─ Frame query API (:8766)           │  │         ┌────────┴────────┐          │
│  Playwright MCP server (:3001/sse)      │  │         ▼                 ▼          │
│                                          │  │  ┌───────────┐   ┌──────────────┐   │
└──────────────────────────────────────────┘  │  │ VoyageAI  │   │ MongoDB Atlas│   │
                                              │  │ (embed +  │   │ (recordings +│   │
                                              │  │  rerank)  │   │ vector search│   │
                                              │  └───────────┘   └──────────────┘   │
                                              │         │                            │
                                              │         ▼                            │
                                              │  ┌──────────────┐                    │
                                              │  │ Google Gemini│                    │
                                              │  │ (LLM)       │                    │
                                              │  └──────────────┘                    │
                                              └──────────────────────────────────────┘
```

### Services

**playwright-browser** — The virtual browser environment. Runs a headless Chromium inside a virtual X11 display (Xvfb). x11vnc + websockify expose VNC over WebSocket for direct user interaction. FFmpeg captures the display and `video_server.py` streams it as MJPEG frames (plus a rolling buffer for historical frame queries). The Playwright MCP server exposes browser automation tools (navigate, click, type, screenshot, snapshot) over SSE.

**python-agent** — The AI engine. A FastAPI server that accepts chat messages over WebSocket. The `BrowserAgent` runs an agentic loop: it sends the user message (plus optional RAG context) to Google Gemini, which responds with structured JSON. If the response contains a tool call, the agent executes it via the MCP client, feeds the result back to Gemini, and repeats (up to 30 iterations). Supports session recording and RAG-based learning from past recordings via MongoDB Atlas + VoyageAI embeddings.

**nextjs-webapp** — The frontend. A Next.js 14 app with two view modes: *Observe* (read-only MJPEG video stream) and *Control* (interactive noVNC session). A chat panel connects to the python-agent over WebSocket. A *Teach* mode lets users record sessions with screenshots and save them with metadata for the RAG pipeline.

### Data Flow (Chat Message)

```
1. User types message in ChatWindow
       │
       ▼  WebSocket
2. python-agent receives message
       │
       ▼
3. RAG context retrieved (if MongoDB + VoyageAI configured)
   ├─ User query → VoyageAI embedding → MongoDB cosine similarity
   ├─ Top-K results → VoyageAI reranking → Top-3
   └─ Load & downsample screenshots → multimodal context
       │
       ▼
4. [user message + RAG context + screenshot] → Gemini LLM
       │
       ▼
5. Gemini responds: { thinking, tool_call, user_message }
       │
       ├─── If tool_call present ──────────────────────┐
       │    Execute via MCP client → Playwright         │
       │    Capture screenshot (if recording)           │
       │    Feed result + screenshot back to Gemini     │
       │    └─── Loop back to step 5 (max 30 iters) ───┘
       │
       ▼
6. Collected user_message fields → WebSocket → ChatWindow
```

### Key Design Patterns

- **Agentic loop** — `agent.py:process_message()` iterates: LLM produces structured JSON, tool calls are executed silently via MCP, results fed back, until the LLM stops requesting tools or limits are hit (30 iterations, 3 retries per step).
- **Shared MCP client** — A single persistent SSE connection to the Playwright MCP server is created at startup and shared across all WebSocket sessions, preventing stale element references.
- **Exponential backoff** — API calls to Gemini retry with jitter on 429 rate limits (`agent.py:_send_message_with_retry`).
- **RAG pipeline** — Two-stage retrieval: vector similarity (K-NN via MongoDB Atlas) then semantic reranking (VoyageAI). Retrieved screenshots are downsampled and injected as multimodal context.
- **Frame buffering** — `video_server.py` maintains a rolling 500ms buffer of MJPEG frames, enabling historical frame queries (used during recording to capture pre-action screenshots).

### File Guide (Suggested Reading Order)

#### Frontend — `services/nextjs-webapp/`

| # | File | What it does |
|---|------|--------------|
| 1 | `src/app/layout.tsx` | Root layout (HTML shell, metadata) |
| 2 | `src/app/page.tsx` | Main page — Observe/Control mode toggle, Teach button, 2-panel layout |
| 3 | `src/components/ChatWindow.tsx` | Chat UI, WebSocket connection to agent, recording state management |
| 4 | `src/components/VideoViewer.tsx` | MJPEG stream display (Observe mode) |
| 5 | `src/hooks/useMJPEGVideoStream.ts` | Custom hook — connects to MJPEG WebSocket, decodes binary frames |
| 6 | `src/components/VNCViewer.tsx` | noVNC remote desktop embed (Control mode) |
| 7 | `src/components/RecordingMetadataModal.tsx` | Modal dialog for saving recording description + tags |

#### Browser — `services/playwright-browser/`

| # | File | What it does |
|---|------|--------------|
| 8 | `entrypoint.sh` | Startup orchestrator — launches Xvfb, x11vnc, websockify, video server, Chromium, Playwright MCP |
| 9 | `video_server.py` | MJPEG streaming server + rolling frame buffer + HTTP frame query API |

#### Agent Core — `services/python-agent/`

| # | File | What it does |
|---|------|--------------|
| 10 | `config.py` | Centralized constants — model names, RAG parameters, image sizes |
| 11 | `models.py` | Pydantic models — `AgentResponse`, `ToolCall` (structured LLM output schema) |
| 12 | `prompts.py` | System prompt builder — formats MCP tool schemas for Gemini |
| 13 | `mcp_client.py` | MCP client wrapper — persistent SSE connection, `call_tool()`, `list_tools()` |
| 14 | `main.py` | FastAPI app — WebSocket `/ws` endpoint, recording endpoints, startup init |
| 15 | `agent.py` | Core `BrowserAgent` — agentic loop, tool execution, retry logic, response parsing |

#### RAG & Storage — `services/python-agent/`

| # | File | What it does |
|---|------|--------------|
| 16 | `recording_models.py` | Pydantic models — `RecordingSession`, `RecordingStep`, `RetrievedRecording` |
| 17 | `voyage_service.py` | VoyageAI wrapper — `embed_document()`, `embed_query()`, `rerank()` |
| 18 | `recording_storage.py` | MongoDB connection — `save_recording()`, `search_similar()` (vector search) |
| 19 | `rag_retriever.py` | RAG pipeline — retrieval + reranking + image loading/downsampling |

#### Reference

| # | File | What it does |
|---|------|--------------|
| 20 | `james-mongoDB-voyageAI.md` | Detailed guide on the MongoDB + VoyageAI RAG integration |

## Prerequisites

- Docker and Docker Compose
- Google Gemini API key

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd watch-and-learn
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your GEMINI_API_KEY
   ```

3. **Build and start the services**
   ```bash
   docker-compose up --build
   ```

4. **Open the application**
   - Navigate to http://localhost:3000
   - You'll see the browser view on the left and chat on the right

## Services

| Service | Port | Description |
|---------|------|-------------|
| nextjs-webapp | 3000 | Main web interface |
| playwright-browser | 6080 | noVNC web interface (direct access) |
| python-agent | 8000 | WebSocket API for agent |

## Usage

### Chat with the Agent
Type commands in the chat window to control the browser:
- "Go to google.com"
- "Search for weather in New York"
- "Click on the first link"
- "What's on the screen?"

### Direct Browser Interaction
Click and type directly in the browser view panel. The AI agent can observe and respond to your actions.

## Development

### Running services individually

**Playwright Browser:**
```bash
cd services/playwright-browser
docker build -t playwright-browser .
docker run -p 6080:6080 -p 3001:3001 playwright-browser
```

**Next.js Webapp:**
```bash
cd services/nextjs-webapp
npm install
npm run dev
```

**Python Agent:**
```bash
cd services/python-agent
pip install -r requirements.txt
GEMINI_API_KEY=your_key python main.py
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| GEMINI_API_KEY | Google Gemini API key | Yes |

## License

MIT
