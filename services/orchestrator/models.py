"""Pydantic models for the Multi-Agent Browser Swarm Orchestrator."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class WorkerStatus(str, Enum):
    """Status of a browser worker instance."""
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"


class TaskStatus(str, Enum):
    """Status of an assigned task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkerConfig(BaseModel):
    """Configuration for a single browser worker."""
    worker_id: int
    agent_port: int = Field(..., description="Python agent API port (800X)")
    video_port: int = Field(..., description="MJPEG video stream port (876X)")
    mcp_port: int = Field(..., description="MCP server port (301X)")
    vnc_port: int = Field(..., description="VNC websockify port (608X)")


class WorkerInstance(BaseModel):
    """Runtime state of a browser worker."""
    config: WorkerConfig
    status: WorkerStatus = WorkerStatus.IDLE
    current_task: Optional[str] = None
    assigned_company: Optional[str] = None
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None


class CompanyInfo(BaseModel):
    """Company information from companies.json."""
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    batch: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    team_size: Optional[str] = None


class TaskResult(BaseModel):
    """Result from a single worker task."""
    worker_id: int
    company_name: str
    valuation: Optional[str] = None
    source: Optional[str] = None
    confidence: str = "Medium"
    raw_response: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None
    duration_seconds: Optional[float] = None


class SwarmCommand(BaseModel):
    """Parsed command from user input."""
    action: str = Field(..., description="Action type: lookup, analyze, compare")
    count: int = Field(default=5, description="Number of companies to process")
    companies: list[str] = Field(default_factory=list, description="Specific companies if named")
    query_type: str = Field(default="valuation", description="Type of data to retrieve")
    raw_input: str = Field(..., description="Original user input")


class OrchestratorStatus(BaseModel):
    """Current status of the orchestrator."""
    total_workers: int
    idle_workers: int
    running_workers: int
    error_workers: int
    active_tasks: int
    completed_tasks: int
    uptime_seconds: float


class TaskRequest(BaseModel):
    """Request to execute a swarm task."""
    command: str = Field(..., description="Natural language command")
    max_workers: Optional[int] = Field(default=None, description="Override default worker count")


class TaskResponse(BaseModel):
    """Response from a swarm task execution."""
    task_id: str
    status: str
    results: list[TaskResult] = Field(default_factory=list)
    markdown_table: Optional[str] = None
    total_duration_seconds: Optional[float] = None
    workers_used: int = 0


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    type: str = Field(..., description="Message type: status, progress, result, error")
    content: str = Field(default="", description="Message content")
    worker_id: Optional[int] = None
    task_id: Optional[str] = None
    data: Optional[dict] = None
