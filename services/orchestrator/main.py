"""Multi-Agent Browser Swarm Orchestrator.

FastAPI service that manages multiple browser agent workers for parallel
company research. Provides REST and WebSocket APIs for task orchestration.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from command_parser import CommandParser
from models import (
    OrchestratorStatus,
    TaskRequest,
    TaskResponse,
    TaskResult,
    TaskStatus,
    WebSocketMessage,
)
from worker_pool import WorkerPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))
COMPANIES_DATA_PATH = os.getenv("COMPANIES_DATA_PATH", "/app/data/companies.json")

# Service Discovery Configuration (external ports exposed to frontend)
ORCHESTRATOR_WS_PORT = int(os.getenv("ORCHESTRATOR_WS_PORT", "8100"))
WORKER_BASE_PORT = int(os.getenv("WORKER_BASE_PORT", "8001"))
VIDEO_STREAM_BASE_PORT = int(os.getenv("VIDEO_STREAM_BASE_PORT", "8766"))
VNC_BASE_PORT = int(os.getenv("VNC_BASE_PORT", "6081"))

# Global state
worker_pool: Optional[WorkerPool] = None
command_parser: Optional[CommandParser] = None
start_time: datetime = datetime.utcnow()
active_connections: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    global worker_pool, command_parser

    logger.info("Starting Multi-Agent Browser Swarm Orchestrator")
    logger.info(f"Max workers: {MAX_WORKERS}")
    logger.info(f"Companies data path: {COMPANIES_DATA_PATH}")

    # Initialize worker pool
    worker_pool = WorkerPool(max_workers=MAX_WORKERS)
    await worker_pool.initialize()

    # Initialize command parser
    from pathlib import Path
    command_parser = CommandParser(companies_path=Path(COMPANIES_DATA_PATH))

    logger.info("Orchestrator initialized successfully")

    yield

    # Shutdown
    logger.info("Shutting down orchestrator")
    if worker_pool:
        await worker_pool.shutdown()


app = FastAPI(
    title="Multi-Agent Browser Swarm Orchestrator",
    description="Orchestrates multiple browser agents for parallel company research",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REST API Endpoints
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "orchestrator"}


@app.get("/services")
async def get_services():
    """Service discovery endpoint - returns all service URLs for frontend.

    This eliminates hardcoded ports in the frontend by providing a single
    source of truth for service locations.
    """
    worker_count = worker_pool.max_workers if worker_pool else MAX_WORKERS

    # Build worker URLs
    workers = []
    for i in range(worker_count):
        workers.append({
            "id": i + 1,
            "ws": f"ws://localhost:{WORKER_BASE_PORT + i}/ws",
            "http": f"http://localhost:{WORKER_BASE_PORT + i}",
        })

    # Build browser/video stream URLs
    browsers = []
    for i in range(worker_count):
        browsers.append({
            "id": i + 1,
            "video_ws": f"ws://localhost:{VIDEO_STREAM_BASE_PORT + i}",
            "vnc_ws": f"ws://localhost:{VNC_BASE_PORT + i}",
        })

    return {
        "orchestrator": {
            "ws": f"ws://localhost:{ORCHESTRATOR_WS_PORT}/ws",
            "http": f"http://localhost:{ORCHESTRATOR_WS_PORT}",
        },
        "workers": workers,
        "browsers": browsers,
        "worker_count": worker_count,
    }


@app.get("/status", response_model=OrchestratorStatus)
async def get_status():
    """Get current orchestrator status."""
    if not worker_pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    pool_status = worker_pool.get_status()
    uptime = (datetime.utcnow() - start_time).total_seconds()

    return OrchestratorStatus(
        total_workers=pool_status["total_workers"],
        idle_workers=pool_status["idle"],
        running_workers=pool_status["running"],
        error_workers=pool_status["error"],
        active_tasks=pool_status["running"],
        completed_tasks=0,  # TODO: Track this
        uptime_seconds=uptime,
    )


@app.get("/workers")
async def get_workers():
    """Get detailed status of all workers."""
    if not worker_pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    return worker_pool.get_status()


@app.get("/companies")
async def get_companies(limit: int = 10):
    """Get list of available companies."""
    if not command_parser:
        raise HTTPException(status_code=503, detail="Command parser not initialized")

    companies = command_parser.companies[:limit]
    return {
        "count": len(companies),
        "total_available": len(command_parser.companies),
        "companies": [c.model_dump() for c in companies],
    }


class ExecuteRequest(BaseModel):
    """Request body for execute endpoint."""
    command: str
    max_workers: Optional[int] = None


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: ExecuteRequest):
    """Execute a swarm task from a natural language command.

    Example commands:
        - "Look up 5 YC companies evaluation value"
        - "Research valuation for first 3 companies"
    """
    if not worker_pool or not command_parser:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    task_id = str(uuid4())[:8]
    start = datetime.utcnow()

    logger.info(f"Task {task_id}: Executing command: {request.command}")

    # Parse the command
    command = command_parser.parse(request.command)
    logger.info(f"Task {task_id}: Parsed - action={command.action}, count={command.count}")

    # Generate task prompts
    task_prompts = command_parser.generate_task_prompts(command)
    logger.info(f"Task {task_id}: Generated {len(task_prompts)} task prompts")

    if not task_prompts:
        return TaskResponse(
            task_id=task_id,
            status="error",
            results=[],
            markdown_table="No companies found to process.",
            workers_used=0,
        )

    # Limit to available workers
    max_workers = request.max_workers or worker_pool.max_workers
    task_prompts = task_prompts[:max_workers]

    # Broadcast task start to WebSocket clients
    await broadcast_message(WebSocketMessage(
        type="status",
        content=f"Starting research on {len(task_prompts)} companies...",
        task_id=task_id,
    ))

    # Execute tasks in parallel
    results = await worker_pool.execute_parallel_tasks(task_prompts)

    # Convert results to response format
    result_dicts = [r.model_dump() for r in results]

    # Generate markdown table
    markdown_table = command_parser.format_results_as_markdown_table(
        result_dicts,
        command.query_type,
    )

    duration = (datetime.utcnow() - start).total_seconds()

    # Add summary to markdown
    completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
    markdown_table += f"\n\n*Research completed in {duration:.1f} seconds using {len(task_prompts)} parallel agents. {completed}/{len(results)} successful.*"

    # Broadcast completion
    await broadcast_message(WebSocketMessage(
        type="result",
        content=markdown_table,
        task_id=task_id,
        data={"results": result_dicts},
    ))

    return TaskResponse(
        task_id=task_id,
        status="completed",
        results=[TaskResult(**r) for r in result_dicts],
        markdown_table=markdown_table,
        total_duration_seconds=duration,
        workers_used=len(task_prompts),
    )


# ============================================================================
# WebSocket API
# ============================================================================


async def broadcast_message(message: WebSocketMessage):
    """Broadcast a message to all connected WebSocket clients."""
    if not active_connections:
        return

    message_data = message.model_dump_json()
    disconnected = []

    for connection in active_connections:
        try:
            await connection.send_text(message_data)
        except Exception as e:
            logger.warning(f"Failed to send message to client: {e}")
            disconnected.append(connection)

    # Remove disconnected clients
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates and command execution."""
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(active_connections)}")

    try:
        # Send initial status
        if worker_pool:
            status = worker_pool.get_status()
            await websocket.send_json({
                "type": "status",
                "content": "Connected to orchestrator",
                "data": {"workers": status},
            })

        while True:
            # Receive message
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type", "")

                if msg_type == "message":
                    # Execute command
                    command_text = message.get("content", "")
                    if command_text:
                        # Run execute_task in background to not block WebSocket
                        asyncio.create_task(
                            handle_websocket_command(websocket, command_text)
                        )

                elif msg_type == "status":
                    # Send status update
                    if worker_pool:
                        status = worker_pool.get_status()
                        await websocket.send_json({
                            "type": "status",
                            "content": "Current status",
                            "data": {"workers": status},
                        })

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "Invalid JSON message",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)


async def handle_websocket_command(websocket: WebSocket, command: str):
    """Handle a command received via WebSocket."""
    if not worker_pool or not command_parser:
        await websocket.send_json({
            "type": "error",
            "content": "Orchestrator not initialized",
        })
        return

    task_id = str(uuid4())[:8]
    start = datetime.utcnow()

    try:
        # Send acknowledgment
        await websocket.send_json({
            "type": "status",
            "content": f"Processing command: {command}",
            "task_id": task_id,
        })

        # Parse command
        parsed = command_parser.parse(command)
        task_prompts = command_parser.generate_task_prompts(parsed)

        if not task_prompts:
            await websocket.send_json({
                "type": "response",
                "content": "No companies found to process. Please check the companies.json file.",
                "task_id": task_id,
            })
            return

        # Limit to available workers
        task_prompts = task_prompts[:worker_pool.max_workers]

        # Send progress update
        await websocket.send_json({
            "type": "status",
            "content": f"Starting parallel research on {len(task_prompts)} companies...",
            "task_id": task_id,
            "data": {
                "companies": [name for name, _ in task_prompts],
            },
        })

        # Execute in parallel
        results = await worker_pool.execute_parallel_tasks(task_prompts)

        # Format results
        result_dicts = [r.model_dump() for r in results]
        markdown_table = command_parser.format_results_as_markdown_table(
            result_dicts,
            parsed.query_type,
        )

        duration = (datetime.utcnow() - start).total_seconds()
        completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        markdown_table += f"\n\n*Research completed in {duration:.1f} seconds using {len(task_prompts)} parallel agents. {completed}/{len(results)} successful.*"

        # Send results
        await websocket.send_json({
            "type": "response",
            "content": markdown_table,
            "task_id": task_id,
            "data": {"results": result_dicts},
        })

    except Exception as e:
        logger.error(f"Error handling WebSocket command: {e}")
        await websocket.send_json({
            "type": "error",
            "content": f"Error processing command: {str(e)}",
            "task_id": task_id,
        })


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
