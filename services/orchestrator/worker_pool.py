"""Worker Pool Manager for the Multi-Agent Browser Swarm.

Manages a pool of persistent browser worker instances for faster task execution.
Workers remain warm (idle) between tasks to avoid cold start delays.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import httpx

from models import (
    WorkerConfig,
    WorkerInstance,
    WorkerStatus,
    TaskResult,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# Port allocation strategy
# Internal ports (inside Docker network) - all workers use same internal port
INTERNAL_AGENT_PORT = 8000  # Workers listen on 8000 internally
# External ports (exposed to host) - Base + worker_id for UI/debugging
BASE_VIDEO_PORT = 8766
BASE_MCP_PORT = 3011
BASE_VNC_PORT = 6081


def generate_worker_config(worker_id: int) -> WorkerConfig:
    """Generate port configuration for a worker based on its ID.

    Note: agent_port uses the INTERNAL port (8000) for Docker network communication.
    The external mapped ports (8001-8006) are only used from outside Docker.
    """
    return WorkerConfig(
        worker_id=worker_id,
        agent_port=INTERNAL_AGENT_PORT,  # All workers use internal port 8000
        video_port=BASE_VIDEO_PORT + worker_id - 1,
        mcp_port=BASE_MCP_PORT + worker_id - 1,
        vnc_port=BASE_VNC_PORT + worker_id - 1,
    )


class WorkerPool:
    """Manages a pool of browser worker instances.

    Attributes:
        max_workers: Maximum number of concurrent workers
        workers: Dictionary of worker instances keyed by worker_id
        http_client: Async HTTP client for worker communication
    """

    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self.workers: dict[int, WorkerInstance] = {}
        self.http_client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize the worker pool with configured workers."""
        self.http_client = httpx.AsyncClient(timeout=60.0)

        logger.info(f"Initializing worker pool with {self.max_workers} workers")

        for i in range(1, self.max_workers + 1):
            config = generate_worker_config(i)
            worker = WorkerInstance(
                config=config,
                status=WorkerStatus.STARTING,
                started_at=datetime.utcnow(),
            )
            self.workers[i] = worker
            logger.info(f"Worker {i} configured: agent={config.agent_port}, video={config.video_port}")

        # Check health of all workers
        await self._check_all_workers_health()

    async def _check_all_workers_health(self):
        """Check health of all workers and update their status."""
        health_checks = []
        for worker_id, worker in self.workers.items():
            health_checks.append(self._check_worker_health(worker_id))

        await asyncio.gather(*health_checks, return_exceptions=True)

    async def _check_worker_health(self, worker_id: int) -> bool:
        """Check if a specific worker is healthy."""
        worker = self.workers.get(worker_id)
        if not worker:
            return False

        try:
            # Try to reach the worker's health endpoint
            url = f"http://worker-{worker_id}:{worker.config.agent_port}/health"
            response = await self.http_client.get(url)

            if response.status_code == 200:
                worker.status = WorkerStatus.IDLE
                worker.last_heartbeat = datetime.utcnow()
                logger.info(f"Worker {worker_id} is healthy")
                return True
            else:
                worker.status = WorkerStatus.ERROR
                logger.warning(f"Worker {worker_id} returned status {response.status_code}")
                return False

        except Exception as e:
            # Worker might not be up yet, that's okay during startup
            worker.status = WorkerStatus.STARTING
            logger.debug(f"Worker {worker_id} not reachable yet: {e}")
            return False

    async def get_idle_workers(self, count: int) -> list[WorkerInstance]:
        """Get up to `count` idle workers for task assignment."""
        async with self._lock:
            idle_workers = [
                w for w in self.workers.values()
                if w.status == WorkerStatus.IDLE
            ]
            return idle_workers[:count]

    async def assign_task(
        self,
        worker_id: int,
        company_name: str,
        task_prompt: str,
    ) -> TaskResult:
        """Assign a task to a specific worker and wait for result."""
        worker = self.workers.get(worker_id)
        if not worker:
            return TaskResult(
                worker_id=worker_id,
                company_name=company_name,
                status=TaskStatus.FAILED,
                error=f"Worker {worker_id} not found",
            )

        if worker.status != WorkerStatus.IDLE:
            return TaskResult(
                worker_id=worker_id,
                company_name=company_name,
                status=TaskStatus.FAILED,
                error=f"Worker {worker_id} is not idle (status: {worker.status})",
            )

        # Mark worker as running
        async with self._lock:
            worker.status = WorkerStatus.RUNNING
            worker.current_task = task_prompt
            worker.assigned_company = company_name

        start_time = datetime.utcnow()

        try:
            # Send task to worker via WebSocket
            url = f"http://worker-{worker_id}:{worker.config.agent_port}/execute"

            response = await self.http_client.post(
                url,
                json={"prompt": task_prompt},
                timeout=120.0,  # 2 minute timeout for browser tasks
            )

            if response.status_code == 200:
                result_data = response.json()
                duration = (datetime.utcnow() - start_time).total_seconds()

                # Parse the response to extract valuation info
                raw_response = result_data.get("response", "")
                valuation, source, confidence = self._parse_valuation_response(raw_response)

                return TaskResult(
                    worker_id=worker_id,
                    company_name=company_name,
                    valuation=valuation,
                    source=source,
                    confidence=confidence,
                    raw_response=raw_response,
                    status=TaskStatus.COMPLETED,
                    duration_seconds=duration,
                )
            else:
                return TaskResult(
                    worker_id=worker_id,
                    company_name=company_name,
                    status=TaskStatus.FAILED,
                    error=f"Worker returned status {response.status_code}",
                    duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                )

        except Exception as e:
            logger.error(f"Error executing task on worker {worker_id}: {e}")
            return TaskResult(
                worker_id=worker_id,
                company_name=company_name,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
            )

        finally:
            # Mark worker as idle again
            async with self._lock:
                worker.status = WorkerStatus.IDLE
                worker.current_task = None
                worker.assigned_company = None

    def _parse_valuation_response(self, response: str) -> tuple[str, str, str]:
        """Parse AI response to extract valuation, source, and confidence.

        Returns:
            Tuple of (valuation, source, confidence)
        """
        valuation = "Unknown"
        source = "Unknown"
        confidence = "Low"

        # Simple heuristic parsing - look for common patterns
        response_lower = response.lower()

        # Look for dollar amounts
        import re
        money_patterns = [
            r'\$[\d,]+(?:\.\d+)?[BMK]?(?:\s*billion)?(?:\s*million)?',
            r'(?:valued at|valuation of|worth)\s*\$?[\d,]+(?:\.\d+)?[BMK]?\s*(?:billion|million)?',
        ]

        for pattern in money_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                valuation = match.group(0).strip()
                confidence = "Medium"
                break

        # Look for sources
        source_patterns = [
            r'(?:according to|source:|from|per)\s+([A-Za-z\s]+?)(?:\.|,|$)',
            r'(?:TechCrunch|Forbes|Bloomberg|Crunchbase|PitchBook|WSJ)',
        ]

        for pattern in source_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                source = match.group(0).strip()
                break

        # Increase confidence if we found both
        if valuation != "Unknown" and source != "Unknown":
            confidence = "High"

        return valuation, source, confidence

    async def execute_parallel_tasks(
        self,
        tasks: list[tuple[str, str]],  # List of (company_name, task_prompt)
    ) -> list[TaskResult]:
        """Execute multiple tasks in parallel across available workers."""
        # Get idle workers
        idle_workers = await self.get_idle_workers(len(tasks))

        if not idle_workers:
            logger.warning("No idle workers available")
            return [
                TaskResult(
                    worker_id=0,
                    company_name=company,
                    status=TaskStatus.FAILED,
                    error="No idle workers available",
                )
                for company, _ in tasks
            ]

        # Assign tasks to workers
        assignments = list(zip(idle_workers, tasks))

        async_tasks = []
        for worker, (company_name, task_prompt) in assignments:
            async_tasks.append(
                self.assign_task(worker.config.worker_id, company_name, task_prompt)
            )

        # Execute in parallel
        results = await asyncio.gather(*async_tasks)

        return list(results)

    def get_status(self) -> dict:
        """Get current status of the worker pool."""
        status_counts = {
            WorkerStatus.IDLE: 0,
            WorkerStatus.RUNNING: 0,
            WorkerStatus.ERROR: 0,
            WorkerStatus.STARTING: 0,
            WorkerStatus.STOPPING: 0,
        }

        for worker in self.workers.values():
            status_counts[worker.status] += 1

        return {
            "total_workers": len(self.workers),
            "idle": status_counts[WorkerStatus.IDLE],
            "running": status_counts[WorkerStatus.RUNNING],
            "error": status_counts[WorkerStatus.ERROR],
            "starting": status_counts[WorkerStatus.STARTING],
            "workers": [
                {
                    "worker_id": w.config.worker_id,
                    "status": w.status.value,
                    "assigned_company": w.assigned_company,
                    "ports": {
                        "agent": w.config.agent_port,
                        "video": w.config.video_port,
                    }
                }
                for w in self.workers.values()
            ]
        }

    async def shutdown(self):
        """Gracefully shutdown the worker pool."""
        logger.info("Shutting down worker pool")

        for worker in self.workers.values():
            worker.status = WorkerStatus.STOPPING

        if self.http_client:
            await self.http_client.aclose()
