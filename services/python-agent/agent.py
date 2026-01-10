import os
import json
import logging
import google.generativeai as genai
from typing import Optional, Union
from mcp_client import MCPClient, MCPToolResult

logger = logging.getLogger(__name__)

# MCP Server URL
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://playwright-browser:3001")


class BrowserAgent:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        self.chat = None
        self.mcp_client: Optional[MCPClient] = None
        self.conversation_history = []

    async def initialize(self):
        """Initialize the agent and connect to MCP server."""
        self.mcp_client = MCPClient(MCP_SERVER_URL)
        await self.mcp_client.connect()

        # Initialize chat with system prompt
        system_prompt = self._build_system_prompt()
        self.conversation_history = [
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": ["Understood. I'm ready to help you interact with the browser. What would you like me to do?"]}
        ]
        self.chat = self.model.start_chat(history=self.conversation_history)

    def _build_system_prompt(self):
        """Build system prompt with available tools."""
        tools = self.mcp_client.get_tools_for_llm() if self.mcp_client else []
        tools_desc = "\n".join([
            f"- **{t['name']}**: {t['description']}"
            for t in tools
        ])

        return f"""You are a helpful browser automation assistant. You can control a web browser to help users accomplish tasks.

## Available Tools
{tools_desc}

## How to Use Tools
When you need to perform an action in the browser, respond with a JSON tool call in this exact format:
```json
{{"tool": "tool_name", "arguments": {{"param1": "value1"}}}}
```

## Important Guidelines
1. Always start by taking a snapshot (browser_snapshot) or screenshot (browser_take_screenshot) to see what's on the page
2. Use the element references from snapshots when clicking or typing
3. After performing an action, take another snapshot or screenshot to see the result
4. Explain what you're doing and what happened to the user
5. Use browser_take_screenshot when you need to visually analyze the page (you'll see the actual image)
6. Use browser_snapshot when you need element references for clicking/typing

## Common Workflows

### Navigate to a website:
```json
{{"tool": "browser_navigate", "arguments": {{"url": "https://example.com"}}}}
```

### Take a screenshot (returns actual image):
```json
{{"tool": "browser_take_screenshot", "arguments": {{}}}}
```

### Click on an element:
```json
{{"tool": "browser_click", "arguments": {{"element": "Search button", "ref": "s12"}}}}
```

### Type text:
```json
{{"tool": "browser_type", "arguments": {{"element": "Search input", "ref": "s10", "text": "hello world"}}}}
```

### Get page content with element refs:
```json
{{"tool": "browser_snapshot", "arguments": {{}}}}
```

Be helpful, proactive, and always explain what you're doing. If something fails, suggest alternatives."""

    async def _execute_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
        """Execute a tool via MCP client and return structured result."""
        if not self.mcp_client:
            return MCPToolResult(error="MCP client not connected")

        try:
            result = await self.mcp_client.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return MCPToolResult(error=f"Error executing tool: {str(e)}")

    def _extract_tool_call(self, text: str) -> Optional[tuple[str, dict]]:
        """Extract tool call from response text."""
        # Look for JSON in the response
        try:
            # Try to find JSON block
            if '```json' in text:
                start = text.find('```json') + 7
                end = text.find('```', start)
                if end > start:
                    json_str = text[start:end].strip()
                    data = json.loads(json_str)
                    if "tool" in data:
                        return data["tool"], data.get("arguments", {})

            # Try to find inline JSON
            if '{"tool"' in text:
                start = text.find('{"tool"')
                # Find matching closing brace
                brace_count = 0
                end = start
                for i, char in enumerate(text[start:], start):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end = i + 1
                            break

                if end > start:
                    json_str = text[start:end]
                    data = json.loads(json_str)
                    if "tool" in data:
                        return data["tool"], data.get("arguments", {})

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool call JSON: {e}")

        return None

    def _build_tool_result_message(self, tool_name: str, result: MCPToolResult) -> list:
        """Build a multimodal message from tool result for Gemini."""
        parts = []

        # Add text description
        if result.error:
            parts.append(f"Tool '{tool_name}' failed with error: {result.error}")
        else:
            text_content = result.get_text()
            if text_content:
                parts.append(f"Tool '{tool_name}' executed. Result:\n```\n{text_content}\n```")
            else:
                parts.append(f"Tool '{tool_name}' executed successfully.")

        # Add images if present (Gemini inline format: dict with mime_type and data)
        for image in result.images:
            parts.append({
                "mime_type": image.mime_type,
                "data": image.data
            })
            logger.info(f"Adding image to message: {image.mime_type}, {len(image.data)} bytes")

        # Add instruction for model
        if result.has_images():
            parts.append("\nI've included a screenshot of the current page. Please describe what you see and continue with the user's request if needed.")
        else:
            parts.append("\nPlease summarize what happened. If you need to perform more actions, include another tool call.")

        return parts

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return a response."""
        try:
            # Send message to Gemini
            response = self.chat.send_message(user_message)
            response_text = response.text

            # Check if response contains a tool call
            tool_call = self._extract_tool_call(response_text)

            if tool_call:
                tool_name, arguments = tool_call
                logger.info(f"Executing tool: {tool_name} with args: {arguments}")

                # Execute the tool
                result = await self._execute_tool(tool_name, arguments)
                result_text = result.get_text()
                logger.info(f"Tool result: {result_text[:500] if result_text else 'No text'}...")

                if result.has_images():
                    logger.info(f"Tool returned {len(result.images)} image(s)")

                # Build multimodal message with text and images
                follow_up_parts = self._build_tool_result_message(tool_name, result)

                # Send multimodal result to Gemini
                follow_up = self.chat.send_message(follow_up_parts)
                follow_up_text = follow_up.text

                # Check if follow-up contains another tool call (for multi-step operations)
                next_tool_call = self._extract_tool_call(follow_up_text)
                if next_tool_call:
                    # Execute the next tool in the chain
                    next_tool_name, next_arguments = next_tool_call
                    logger.info(f"Executing follow-up tool: {next_tool_name}")

                    next_result = await self._execute_tool(next_tool_name, next_arguments)

                    # Build multimodal message for next result
                    final_parts = self._build_tool_result_message(next_tool_name, next_result)
                    final_parts.append("\nProvide a final summary for the user.")

                    final_summary = self.chat.send_message(final_parts)
                    return final_summary.text

                return follow_up_text

            return response_text

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise

    async def cleanup(self):
        """Cleanup resources."""
        if self.mcp_client:
            await self.mcp_client.disconnect()
