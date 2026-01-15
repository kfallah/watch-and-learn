import asyncio
import json
import logging
import os

from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent import BrowserAgent
from mcp_client import MCPClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Watch and Learn Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active connections and their agents
active_connections: dict[str, tuple[WebSocket, BrowserAgent]] = {}

# Shared MCP client for all agents

shared_mcp_client: MCPClient | None = None
shared_mcp_lock: asyncio.Lock | None = None

# Global recording agent for manual control mode
recording_agent: BrowserAgent | None = None
recording_agent_lock: asyncio.Lock | None = None


@app.on_event("startup")
async def startup_event():
    global recording_agent_lock, shared_mcp_lock, shared_mcp_client
    recording_agent_lock = asyncio.Lock()
    shared_mcp_lock = asyncio.Lock()

    # Initialize shared MCP client on startup with retries
    logger.info("Initializing shared MCP client on startup")
    max_retries = 10
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            shared_mcp_client = MCPClient(os.getenv("MCP_SERVER_URL", "http://playwright-browser:3001"))
            await shared_mcp_client.connect()
            logger.info("Shared MCP client initialized successfully")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Failed to connect to MCP server (attempt {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to MCP server after {max_retries} attempts")
                raise


async def get_shared_mcp_client() -> MCPClient:
    """Get the shared MCP client."""
    global shared_mcp_client

    if shared_mcp_client is None:
        raise RuntimeError("Shared MCP client not initialized. This should not happen.")

    return shared_mcp_client


async def _process_and_respond(
    agent: BrowserAgent,
    websocket: WebSocket,
    user_content: str
) -> None:
    """Process a message and send the response. Runs as a background task."""
    try:
        # Check if we should inject demo content (first message only)
        if not agent.demo_injected:
            demo_metadata = await agent.inject_demo_content()
            if demo_metadata:
                await websocket.send_json({
                    "type": "memory_injected",
                    "metadata": demo_metadata
                })
                logger.info("Sent memory_injected message to client")

        # Send status update
        await websocket.send_json({
            "type": "status",
            "content": "thinking"
        })

        # Process with agent
        response = await agent.process_message(user_content)
        await websocket.send_json({
            "type": "response",
            "content": response
        })
    except Exception as e:
        logger.error(f"Agent error: {e}")
        await websocket.send_json({
            "type": "response",
            "content": f"Sorry, I encountered an error: {str(e)}"
        })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connection_id = str(id(websocket))

    # Create agent for this connection with shared MCP client
    agent = BrowserAgent()
    agent.mcp_client = await get_shared_mcp_client()
    # Initialize chat without reinitializing MCP
    system_prompt = agent._build_system_prompt()
    agent.conversation_history = [
        {"role": "user", "parts": [system_prompt]},
        {"role": "model", "parts": ["Understood. I'm ready to help you interact with the browser. What would you like me to do?"]}
    ]
    agent.chat = agent.model.start_chat(history=agent.conversation_history)
    active_connections[connection_id] = (websocket, agent)

    logger.info(f"Client connected: {connection_id}")

    # Track the current processing task
    processing_task: asyncio.Task | None = None

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "set_recording":
                # Handle recording state change
                is_recording = message.get("recording", False)
                agent.set_recording(is_recording)
                logger.info(f"Recording state changed to: {is_recording}")
                await websocket.send_json({
                    "type": "recording_status",
                    "recording": is_recording,
                    "session_id": agent.recording_session_id
                })

            elif message.get("type") == "interrupt":
                # User wants to interrupt with additional context
                context = message.get("content", "")
                if processing_task and not processing_task.done():
                    await agent.interrupt(context)
                    await websocket.send_json({
                        "type": "status",
                        "content": "interrupt_received"
                    })
                    logger.info(f"Interrupt queued with context: {context[:50]}...")
                else:
                    logger.warning("Interrupt received but no active processing task")
                    await websocket.send_json({
                        "type": "status",
                        "content": "no_active_task"
                    })

            elif message.get("type") == "message":
                user_content = message.get("content", "")
                logger.info(f"Received message: {user_content}")

                # Check if already processing - treat as interrupt
                if processing_task and not processing_task.done():
                    await agent.interrupt(user_content)
                    await websocket.send_json({
                        "type": "status",
                        "content": "interrupt_received"
                    })
                    logger.info(f"Message queued as interrupt: {user_content[:50]}...")
                else:
                    # Start new processing task
                    processing_task = asyncio.create_task(
                        _process_and_respond(agent, websocket, user_content)
                    )

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cancel any running task
        if processing_task and not processing_task.done():
            processing_task.cancel()
        # Cleanup - don't disconnect shared MCP client
        if connection_id in active_connections:
            del active_connections[connection_id]


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


async def get_or_create_recording_agent() -> BrowserAgent:
    """Get or create the global recording agent with shared MCP client."""
    global recording_agent

    assert recording_agent_lock is not None, "recording_agent_lock not initialized"
    async with recording_agent_lock:
        if recording_agent is None:
            logger.info("Creating new recording agent")
            recording_agent = BrowserAgent()
            recording_agent.mcp_client = await get_shared_mcp_client()
            # Initialize chat without reinitializing MCP
            system_prompt = recording_agent._build_system_prompt()
            recording_agent.conversation_history = [
                {"role": "user", "parts": [system_prompt]},
                {"role": "model", "parts": ["Understood. I'm ready to help you interact with the browser. What would you like me to do?"]}
            ]
            recording_agent.chat = recording_agent.model.start_chat(history=recording_agent.conversation_history)
            logger.info("Recording agent initialized with shared MCP client")
        return recording_agent


@app.post("/recording/start")
async def start_recording():
    """Enable recording mode"""
    agent = await get_or_create_recording_agent()
    agent.set_recording(True)
    return {
        "status": "recording",
        "recording": True,
        "session_id": agent.recording_session_id
    }


@app.post("/recording/stop")
async def stop_recording():
    """Disable recording mode"""
    global recording_agent

    if recording_agent:
        recording_agent.set_recording(False)

    return {"status": "stopped", "recording": False}


@app.post("/recording/screenshot")
async def capture_screenshot(event_type: str = "manual"):
    """Capture a screenshot during manual control"""
    agent = await get_or_create_recording_agent()

    if agent.is_recording:
        filename = await agent._capture_screenshot(event_type)
        return {"status": "captured", "filename": filename}

    return {"status": "not_recording", "filename": None}


@app.post("/recording/metadata")
async def save_recording_metadata(session_id: str = Form(...), description: str = Form(...)):
    """Save metadata for a recording session"""
    import re
    from datetime import datetime

    # Validate session_id format (timestamp_uuid)
    if not re.match(r'^\d{8}_\d{6}_[a-f0-9]{8}$', session_id):
        return {"status": "error", "message": "Invalid session_id format"}, 400

    # Validate description is non-empty
    if not description.strip():
        return {"status": "error", "message": "Description is required"}, 400

    try:
        # Create metadata object
        metadata = {
            "session_id": session_id,
            "description": description.strip(),
            "created_at": datetime.now().isoformat()
        }

        # Save to JSON file
        metadata_path = f"/tmp/screenshots/{session_id}_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Metadata saved for session {session_id}: {description[:50]}...")
        return {"status": "success", "metadata_path": metadata_path}

    except Exception as e:
        logger.error(f"Error saving metadata: {e}")
        return {"status": "error", "message": str(e)}, 500


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
