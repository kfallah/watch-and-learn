import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict


@dataclass
class MCPImageContent:
    """Represents image content returned from MCP tool."""
    data: bytes  # Raw image bytes
    mime_type: str

    @classmethod
    def from_mcp_content(cls, content: dict) -> Optional["MCPImageContent"]:
        """Create from MCP content dict with type='image'."""
        if content.get("type") == "image":
            data = content.get("data", "")
            mime_type = content.get("mimeType", "image/png")
            try:
                image_bytes = base64.b64decode(data)
                return cls(data=image_bytes, mime_type=mime_type)
            except Exception as e:
                logger.error(f"Failed to decode image data: {e}")
        return None


@dataclass
class MCPToolResult:
    """Result from an MCP tool call, containing text and/or images."""
    text_content: list[str] = field(default_factory=list)
    images: list[MCPImageContent] = field(default_factory=list)
    raw_result: dict = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_mcp_response(cls, result: dict) -> "MCPToolResult":
        """Parse MCP tool response into structured result."""
        tool_result = cls(raw_result=result)

        if "error" in result:
            tool_result.error = str(result["error"])
            return tool_result

        # Parse content array from MCP response
        content_list = result.get("content", [])
        if not isinstance(content_list, list):
            content_list = [content_list]

        for content in content_list:
            if not isinstance(content, dict):
                tool_result.text_content.append(str(content))
                continue

            content_type = content.get("type", "text")

            if content_type == "text":
                tool_result.text_content.append(content.get("text", ""))
            elif content_type == "image":
                image = MCPImageContent.from_mcp_content(content)
                if image:
                    tool_result.images.append(image)
                    logger.info(f"Parsed image content: {image.mime_type}, {len(image.data)} bytes")

        return tool_result

    def has_images(self) -> bool:
        """Check if result contains any images."""
        return len(self.images) > 0

    def get_text(self) -> str:
        """Get combined text content."""
        return "\n".join(self.text_content)

    def to_gemini_parts(self) -> list:
        """Convert to Gemini API multimodal parts format."""
        parts = []

        # Add text content
        if self.text_content:
            parts.append(self.get_text())

        # Add images in Gemini inline format
        for image in self.images:
            parts.append({
                "mime_type": image.mime_type,
                "data": image.data
            })

        return parts


class MCPClient:
    """Client for communicating with MCP server over Streamable HTTP transport."""

    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip('/')
        self.http_client: httpx.AsyncClient | None = None
        self.tools: list[MCPTool] = []
        self._request_id = 0
        self._session_id: str | None = None

    async def connect(self):
        """Connect to the MCP server using Streamable HTTP transport."""
        self.http_client = httpx.AsyncClient(timeout=60.0)

        # Initialize connection
        try:
            # Send initialize request - POST directly to root with proper headers
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

    async def _send_request(self, method: str, params: dict, retry_on_session_error: bool = True) -> dict | None:
        """Send a JSON-RPC request to the MCP server using Streamable HTTP."""
        if not self.http_client:
            raise RuntimeError("MCP client not connected")

        request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        # Add session ID if we have one
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            # POST to root endpoint for Streamable HTTP transport
            response = await self.http_client.post(
                f"{self.server_url}/mcp",
                json=request,
                headers=headers
            )

            # Store session ID from response if provided
            if "mcp-session-id" in response.headers:
                self._session_id = response.headers["mcp-session-id"]
                logger.debug(f"Got session ID: {self._session_id}")

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")

                if "text/event-stream" in content_type:
                    # Parse SSE response
                    return await self._parse_sse_response(response.text)
                else:
                    # Direct JSON response
                    result = response.json()
                    if "error" in result:
                        logger.error(f"MCP error: {result['error']}")
                        return None
                    return result.get("result")
            elif response.status_code == 202:
                # Accepted - response will come via SSE
                logger.info("Request accepted, awaiting SSE response")
                return None
            elif response.status_code == 404 and retry_on_session_error:
                # Session expired/not found - clear session and retry
                logger.warning("Session expired, reconnecting...")
                self._session_id = None
                await self._reinitialize_session()
                return await self._send_request(method, params, retry_on_session_error=False)
            else:
                logger.error(f"MCP request failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"MCP request error: {e}")
            return None

    async def _reinitialize_session(self):
        """Re-initialize the MCP session."""
        try:
            init_response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "watch-and-learn-agent",
                    "version": "1.0.0"
                }
            }, retry_on_session_error=False)
            logger.info(f"MCP re-initialized: {init_response}")
            await self._send_notification("notifications/initialized", {})
        except Exception as e:
            logger.error(f"Failed to reinitialize MCP session: {e}")

    async def _parse_sse_response(self, text: str) -> dict | None:
        """Parse SSE response to extract JSON-RPC result."""
        for line in text.split('\n'):
            if line.startswith('data: '):
                try:
                    data = json.loads(line[6:])
                    if "result" in data:
                        return data["result"]
                    elif "error" in data:
                        logger.error(f"MCP SSE error: {data['error']}")
                        return None
                except json.JSONDecodeError:
                    continue
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

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            await self.http_client.post(
                f"{self.server_url}/mcp",
                json=notification,
                headers=headers
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    async def call_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
        """Call a tool on the MCP server and return structured result."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        if result:
            return MCPToolResult.from_mcp_response(result)
        return MCPToolResult(error=f"Failed to execute tool: {tool_name}")

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
