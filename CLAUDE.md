# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Watch and Learn is a Docker Compose application that lets users watch and interact with a browser controlled by an AI agent. It features hybrid control (chat with the agent OR directly interact with the browser), session recording with screenshot capture, and RAG-based retrieval of past recordings to inform future tasks.

## Architecture

Three Docker services communicate over an internal bridge network:

- **playwright-browser** — Runs Xvfb + Chromium + x11vnc + websockify + FFmpeg video server + Playwright MCP server. Provides the virtual browser environment. Exposes VNC via websockify on `:6080`, MJPEG video stream on `:8765`, frame query HTTP API on `:8766`, and MCP (SSE) on `:3001`.
- **python-agent** — FastAPI app (`:8000`) that hosts the AI agent. Connects to the Playwright MCP server to control the browser. Uses Google Gemini (`gemini-2.0-flash`) as the LLM with structured JSON responses. Supports RAG via MongoDB Atlas + Voyage AI embeddings. Communicates with the webapp over WebSocket (`/ws`).
- **nextjs-webapp** — Next.js 14 frontend (`:3000`). Two view modes: "Observe" (MJPEG video stream) and "Control" (noVNC for direct browser interaction). Chat panel sends/receives messages via WebSocket to python-agent. Supports "Teach" mode for recording sessions.

### Data Flow

1. User sends chat message → WebSocket → python-agent
2. Agent queries RAG context (MongoDB + Voyage AI embeddings) if available
3. Agent sends message + context to Gemini, gets structured JSON response (`{thinking, tool_call, user_message}`)
4. If `tool_call` present → execute via MCP client → feed result back to Gemini → loop (max 30 iterations)
5. When recording, screenshots are captured from the video buffer before browser actions
6. Collected `user_message` fields are returned to the frontend

### Key Design Patterns

- **Agentic loop**: `agent.py:process_message()` runs a tool-execution loop with Gemini. The LLM responds with structured JSON; tool calls are executed silently until the LLM stops requesting them or limits are hit (MAX_ITERATIONS=30, MAX_RETRIES_PER_STEP=3).
- **Shared MCP client**: A single persistent SSE connection to the Playwright MCP server is shared across all WebSocket connections to prevent stale element references.
- **Exponential backoff**: API calls to Gemini use retry with jitter for 429 rate limiting (agent.py `_send_message_with_retry`).
- **RAG pipeline**: User query → Voyage AI embedding → cosine similarity search in MongoDB → Voyage AI reranking → load & downsample screenshots → inject as multimodal context into Gemini conversation.

## Common Commands

### Run the full stack
```bash
cp .env.example .env  # add GEMINI_API_KEY
docker-compose up --build
```
App available at http://localhost:3000

### Run services individually (development)

**Next.js webapp:**
```bash
cd services/nextjs-webapp && npm install && npm run dev
```

**Python agent (outside Docker):**
```bash
cd services/python-agent && pip install -r requirements.txt
GEMINI_API_KEY=your_key python main.py
```

### Linting Requirements

**IMPORTANT**: Always run these linting tools after making any changes to Python code in `services/python-agent/`:

#### Ruff (Linting & Formatting)
```bash
cd services/python-agent && uvx ruff check --fix .
```

#### ty (Type Checking)
```bash
cd services/python-agent && uvx ty check .
```

Note: `pyproject.toml` configures `ty` to ignore unresolved imports since dependencies are installed in the Docker container.

### Next.js lint
```bash
cd services/nextjs-webapp && npm run lint
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `VOYAGE_API_KEY` | Voyage AI API key (for RAG embeddings/reranking) | No (RAG disabled without it) |
| `MONGODB_URI` | MongoDB Atlas connection string | No (recording storage disabled without it) |
| `DEMO_ENABLED` | Load demo images from `./demo/` as context (`true`/`false`) | No (default: `false`) |

## Key Files

- `services/python-agent/agent.py` — Core `BrowserAgent` class with agentic loop, tool execution, RAG context building, and response parsing
- `services/python-agent/main.py` — FastAPI app with WebSocket endpoint, recording endpoints, and startup initialization
- `services/python-agent/mcp_client.py` — MCP client using official `mcp` library with persistent SSE transport
- `services/python-agent/prompts.py` — System prompt builder that formats MCP tool schemas for Gemini
- `services/python-agent/models.py` — Pydantic models for structured LLM responses (`AgentResponse`, `ToolCall`)
- `services/python-agent/rag_retriever.py` — RAG retrieval with image loading and downsampling
- `services/python-agent/voyage_service.py` — Voyage AI wrapper for embeddings and reranking
- `services/python-agent/recording_storage.py` — MongoDB storage with cosine similarity search
- `services/python-agent/config.py` — Centralized configuration (model names, RAG parameters, image sizes)
- `services/playwright-browser/entrypoint.sh` — Starts all browser container services (Xvfb, VNC, websockify, FFmpeg video server, Chromium, Playwright MCP)
- `services/playwright-browser/video_server.py` — MJPEG streaming + rolling frame buffer for historical frame queries
- `services/nextjs-webapp/src/app/page.tsx` — Main page with Observe/Control mode toggle and Teach button
- `services/nextjs-webapp/src/components/ChatWindow.tsx` — WebSocket chat with recording state management
