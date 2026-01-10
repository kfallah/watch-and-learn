import asyncio
import json
import logging
import httpx
from typing import Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict


class MCPClient:
    """Client for communicating with MCP server over SSE transport."""

    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip('/')
        self.http_client: Optional[httpx.AsyncClient] = None
        self.tools: list[MCPTool] = []
        self._request_id = 0

    async def connect(self):
        """Connect to the MCP server."""
        self.http_client = httpx.AsyncClient(timeout=60.0)

        # Initialize connection
        try:
            # Send initialize request
            init_response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "watch-and-learn-agent",
                    "version": "1.0.0"
                }
            })
            logger.info(f"MCP initialized: {init_response}")

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            # List available tools
            tools_response = await self._send_request("tools/list", {})
            if tools_response and "tools" in tools_response:
                self.tools = [
                    MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {})
                    )
                    for t in tools_response["tools"]
                ]
                logger.info(f"Loaded {len(self.tools)} tools from MCP server")

        except Exception as e:
            logger.error(f"Failed to initialize MCP connection: {e}")
            # Use fallback tools if connection fails
            self.tools = self._get_fallback_tools()

    def _get_fallback_tools(self) -> list[MCPTool]:
        """Fallback tools when MCP server is not available."""
        return [
            MCPTool(
                name="browser_navigate",
                description="Navigate to a URL",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"}
                    },
                    "required": ["url"]
                }
            ),
            MCPTool(
                name="browser_click",
                description="Click on an element",
                input_schema={
                    "type": "object",
                    "properties": {
                        "element": {"type": "string", "description": "Element description"},
                        "ref": {"type": "string", "description": "Element reference"}
                    },
                    "required": ["element", "ref"]
                }
            ),
            MCPTool(
                name="browser_type",
                description="Type text into an element",
                input_schema={
                    "type": "object",
                    "properties": {
                        "element": {"type": "string", "description": "Element description"},
                        "ref": {"type": "string", "description": "Element reference"},
                        "text": {"type": "string", "description": "Text to type"}
                    },
                    "required": ["element", "ref", "text"]
                }
            ),
            MCPTool(
                name="browser_snapshot",
                description="Get accessibility snapshot of the page",
                input_schema={
                    "type": "object",
                    "properties": {}
                }
            )
        ]

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(self, method: str, params: dict) -> Optional[dict]:
        """Send a JSON-RPC request to the MCP server."""
        if not self.http_client:
            raise RuntimeError("MCP client not connected")

        request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params
        }

        try:
            response = await self.http_client.post(
                f"{self.server_url}/message",
                json=request,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                result = response.json()
                if "error" in result:
                    logger.error(f"MCP error: {result['error']}")
                    return None
                return result.get("result")
            else:
                logger.error(f"MCP request failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"MCP request error: {e}")
            return None

    async def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        if not self.http_client:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        try:
            await self.http_client.post(
                f"{self.server_url}/message",
                json=notification,
                headers={"Content-Type": "application/json"}
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        if result:
            return result
        return {"error": f"Failed to execute tool: {tool_name}"}

    def get_tools_for_llm(self) -> list[dict]:
        """Get tool definitions in a format suitable for LLM function calling."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema
            }
            for tool in self.tools
        ]

    async def disconnect(self):
        """Disconnect from the MCP server."""
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None
