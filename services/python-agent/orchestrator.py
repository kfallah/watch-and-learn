"""Orchestrator for multi-agent swarm execution.

Handles prompt parsing, task distribution, claim coordination, and result synthesis.
"""

# James code
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum

import google.generativeai as genai
import httpx

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Type of swarm task."""

    PRE_ASSIGNED = "pre_assigned"  # Specific items listed in prompt
    DYNAMIC_DISCOVERY = "dynamic_discovery"  # Agents find items themselves
    COMPARATIVE = "comparative"  # Need to compare results


class AgentStatus(Enum):
    """Status of an agent in the swarm."""

    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    ERROR = "error"


@dataclass
class TaskPlan:
    """Plan for executing a swarm task."""

    task_type: TaskType
    original_prompt: str
    target_count: int
    sub_tasks: list[str] = field(default_factory=list)  # Pre-assigned tasks
    base_task: str = ""  # For dynamic discovery: "find a YC company"
    comparison_criteria: str = ""  # For comparative: "highest valuation"


@dataclass
class AgentResult:
    """Result from a single agent."""

    agent_id: int
    claimed_item: str | None
    result: str
    status: AgentStatus
    error: str | None = None


class Orchestrator:
    """Coordinates multiple agents for parallel task execution."""

    def __init__(self, worker_count: int = 6):
        self.worker_count = worker_count
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("models/gemini-3-pro-preview")

        # State for current swarm execution
        self.claimed_items: set[str] = set()
        self.claims_lock = asyncio.Lock()
        self.agent_results: dict[int, AgentResult] = {}
        self.agent_statuses: dict[int, AgentStatus] = {}
        self.current_plan: TaskPlan | None = None

        # HTTP client for communicating with workers
        self.http_client = httpx.AsyncClient(timeout=120.0)

        # Status update callback (set by main.py for WebSocket updates)
        self.on_status_update: callable | None = None

    async def parse_prompt(self, prompt: str) -> TaskPlan:
        """Use Gemini to analyze the prompt and create an execution plan."""
        parse_prompt = f"""Analyze this user request and determine how to execute it with multiple browser agents.

User request: "{prompt}"

Determine:
1. task_type: One of:
   - "pre_assigned": The user specified exact items (e.g., "look up Stripe, Airbnb, Dropbox")
   - "dynamic_discovery": The user wants N items but didn't specify which (e.g., "find 5 YC companies")
   - "comparative": The user wants to compare and find the best (e.g., "which YC company has highest valuation")

2. target_count: How many items/agents needed (1-6)

3. For pre_assigned: List the specific sub-tasks, one per agent
   For dynamic_discovery: Provide the base task each agent should do
   For comparative: Provide both base task and comparison criteria

Respond in JSON format:
{{
    "task_type": "pre_assigned" | "dynamic_discovery" | "comparative",
    "target_count": <number 1-6>,
    "sub_tasks": ["task1", "task2", ...],  // Only for pre_assigned
    "base_task": "...",  // For dynamic_discovery and comparative
    "comparison_criteria": "..."  // Only for comparative
}}

Examples:

Input: "Look up Stripe, Airbnb, and Coinbase"
Output: {{"task_type": "pre_assigned", "target_count": 3, "sub_tasks": ["Research Stripe company - find their valuation, founders, and what they do", "Research Airbnb company - find their valuation, founders, and what they do", "Research Coinbase company - find their valuation, founders, and what they do"]}}

Input: "Find 5 YC companies"
Output: {{"task_type": "dynamic_discovery", "target_count": 5, "base_task": "Find and research one YC company. Look up their valuation, founders, and what they do. Pick a company that hasn't been claimed yet."}}

Input: "Which YC company has the highest valuation?"
Output: {{"task_type": "comparative", "target_count": 6, "base_task": "Find and research one YC company. Focus on finding their current valuation.", "comparison_criteria": "highest valuation"}}
"""

        try:
            response = await self.model.generate_content_async(parse_prompt)
            response_text = response.text

            # Parse JSON from response
            json_str = response_text
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_str = response_text[start:end].strip()
            elif response_text.strip().startswith("{"):
                json_str = response_text.strip()

            data = json.loads(json_str)

            plan = TaskPlan(
                task_type=TaskType(data["task_type"]),
                original_prompt=prompt,
                target_count=min(data.get("target_count", 1), self.worker_count),
                sub_tasks=data.get("sub_tasks", []),
                base_task=data.get("base_task", ""),
                comparison_criteria=data.get("comparison_criteria", ""),
            )

            logger.info(f"Parsed prompt into plan: {plan}")
            return plan

        except Exception as e:
            logger.error(f"Error parsing prompt: {e}")
            # Fallback to simple pre-assigned task
            return TaskPlan(
                task_type=TaskType.PRE_ASSIGNED,
                original_prompt=prompt,
                target_count=1,
                sub_tasks=[prompt],
            )

    async def claim_item(self, agent_id: int, item: str) -> bool:
        """Agent requests to claim an item. Returns True if approved."""
        async with self.claims_lock:
            # Normalize item name for comparison
            normalized = item.lower().strip()

            # Check if already claimed
            if normalized in self.claimed_items:
                logger.info(f"Agent {agent_id} denied claim for '{item}' - already claimed")
                return False

            # Approve the claim
            self.claimed_items.add(normalized)
            logger.info(f"Agent {agent_id} claimed '{item}'")

            # Update status
            if agent_id in self.agent_results:
                self.agent_results[agent_id].claimed_item = item

            await self._broadcast_status()
            return True

    async def submit_result(self, agent_id: int, result: str, claimed_item: str | None = None):
        """Agent submits its result."""
        self.agent_results[agent_id] = AgentResult(
            agent_id=agent_id,
            claimed_item=claimed_item,
            result=result,
            status=AgentStatus.DONE,
        )
        self.agent_statuses[agent_id] = AgentStatus.DONE
        logger.info(f"Agent {agent_id} submitted result for '{claimed_item}'")
        await self._broadcast_status()

    async def submit_error(self, agent_id: int, error: str):
        """Agent reports an error."""
        self.agent_results[agent_id] = AgentResult(
            agent_id=agent_id,
            claimed_item=None,
            result="",
            status=AgentStatus.ERROR,
            error=error,
        )
        self.agent_statuses[agent_id] = AgentStatus.ERROR
        logger.error(f"Agent {agent_id} reported error: {error}")
        await self._broadcast_status()

    async def synthesize(self) -> str:
        """Combine all results into a final response."""
        if not self.current_plan:
            return "No task plan found."

        results = [r for r in self.agent_results.values() if r.status == AgentStatus.DONE]

        if not results:
            return "No results collected from agents."

        # Build context for synthesis
        results_text = "\n\n".join([
            f"### {r.claimed_item or f'Agent {r.agent_id}'}\n{r.result}"
            for r in results
        ])

        if self.current_plan.task_type == TaskType.COMPARATIVE:
            # Need to compare and pick winner
            synthesis_prompt = f"""Based on these research results, answer the user's original question.

Original question: "{self.current_plan.original_prompt}"
Comparison criteria: {self.current_plan.comparison_criteria}

Results from research:
{results_text}

Provide a clear answer identifying the winner based on the comparison criteria, with supporting evidence from the research."""

        else:
            # Simple aggregation
            synthesis_prompt = f"""Summarize these research results into a cohesive response.

Original request: "{self.current_plan.original_prompt}"

Results from research:
{results_text}

Provide a clear, organized summary of all findings. Use a table format if appropriate."""

        try:
            response = await self.model.generate_content_async(synthesis_prompt)
            return response.text
        except Exception as e:
            logger.error(f"Error synthesizing results: {e}")
            return f"## Results\n\n{results_text}"

    async def execute_swarm(self, prompt: str) -> str:
        """Execute a swarm task from start to finish."""
        # Reset state
        self.claimed_items.clear()
        self.agent_results.clear()
        self.agent_statuses.clear()

        # Parse the prompt
        self.current_plan = await self.parse_prompt(prompt)
        plan = self.current_plan

        logger.info(f"Starting swarm execution: {plan.task_type.value}, {plan.target_count} agents")
        await self._broadcast_status()

        # Prepare tasks for each agent
        tasks = []
        for i in range(plan.target_count):
            agent_id = i + 1
            self.agent_statuses[agent_id] = AgentStatus.WORKING

            if plan.task_type == TaskType.PRE_ASSIGNED:
                # Each agent gets a specific task
                if i < len(plan.sub_tasks):
                    task_prompt = plan.sub_tasks[i]
                else:
                    continue
            else:
                # Dynamic discovery or comparative - all agents get same base task
                task_prompt = self._build_dynamic_task_prompt(plan, agent_id)

            tasks.append(self._execute_agent_task(agent_id, task_prompt))

        await self._broadcast_status()

        # Execute all tasks in parallel
        await asyncio.gather(*tasks, return_exceptions=True)

        # Synthesize results
        final_response = await self.synthesize()

        logger.info("Swarm execution completed")
        return final_response

    def _build_dynamic_task_prompt(self, plan: TaskPlan, agent_id: int) -> str:
        """Build task prompt for dynamic discovery agents."""
        claimed_list = ", ".join(self.claimed_items) if self.claimed_items else "none yet"

        prompt = f"""{plan.base_task}

IMPORTANT: Before researching any company, you must claim it first to avoid duplicates.
Already claimed by other agents: {claimed_list}

To claim a company, include in your response:
CLAIM: <company name>

Only proceed with research after your claim is confirmed.
If your claim is rejected (company already taken), try a different company.

You are Agent {agent_id} of {plan.target_count}."""

        return prompt

    async def _execute_agent_task(self, agent_id: int, task_prompt: str):
        """Execute a task on a specific agent worker."""
        worker_host = f"worker-{agent_id}"
        url = f"http://{worker_host}:8000/execute"

        try:
            logger.info(f"Sending task to agent {agent_id}: {task_prompt[:100]}...")

            response = await self.http_client.post(
                url,
                json={"prompt": task_prompt},
            )

            if response.status_code == 200:
                data = response.json()
                result = data.get("response", "")

                # Extract claimed item from result if present
                claimed_item = self._extract_claimed_item(result)

                await self.submit_result(agent_id, result, claimed_item)
            else:
                await self.submit_error(agent_id, f"HTTP {response.status_code}")

        except Exception as e:
            logger.error(f"Error executing task on agent {agent_id}: {e}")
            await self.submit_error(agent_id, str(e))

    def _extract_claimed_item(self, result: str) -> str | None:
        """Extract claimed item from agent result."""
        # Look for "CLAIM: <item>" pattern
        import re
        match = re.search(r"CLAIM:\s*(.+?)(?:\n|$)", result, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Fallback: try to extract company name from context
        # This is a simple heuristic
        return None

    async def _broadcast_status(self):
        """Broadcast current status to connected clients."""
        if self.on_status_update:
            status = self.get_status()
            await self.on_status_update(status)

    def get_status(self) -> dict:
        """Get current swarm status."""
        return {
            "plan": {
                "task_type": self.current_plan.task_type.value if self.current_plan else None,
                "target_count": self.current_plan.target_count if self.current_plan else 0,
                "original_prompt": self.current_plan.original_prompt if self.current_plan else "",
            } if self.current_plan else None,
            "claimed_items": list(self.claimed_items),
            "agents": {
                agent_id: {
                    "status": status.value,
                    "claimed_item": self.agent_results.get(agent_id, AgentResult(agent_id, None, "", AgentStatus.IDLE)).claimed_item,
                    "has_result": agent_id in self.agent_results and self.agent_results[agent_id].status == AgentStatus.DONE,
                }
                for agent_id, status in self.agent_statuses.items()
            },
        }

    async def cleanup(self):
        """Cleanup resources."""
        await self.http_client.aclose()
