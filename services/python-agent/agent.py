import json
import logging
import os
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types.content import Part as GenaiPart
from pydantic import ValidationError

from mcp_client import MCPClient, MCPToolResult
from models import AgentResponse
from prompts import (
    TOOL_RESULT_REMINDER,
    TOOL_RESULT_REMINDER_WITH_IMAGE,
    build_system_prompt,
)

logger = logging.getLogger(__name__)

# MCP Server URL
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://playwright-browser:3001")

# Maximum iterations for the agentic loop to prevent infinite loops
MAX_ITERATIONS = 10

# Logs directory for dumping context
LOGS_DIR = Path("/app/logs")


class BrowserAgent:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        self.chat = None
        self.mcp_client: MCPClient | None = None
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

    def _build_system_prompt(self) -> str:
        """Build system prompt with available tools and their parameter schemas."""
        tools = self.mcp_client.get_tools_for_llm() if self.mcp_client else []
        return build_system_prompt(tools)

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

    def _parse_response(self, text: str) -> AgentResponse:
        """Parse LLM response into structured AgentResponse.

        Attempts to extract JSON from the response and validate it against
        the AgentResponse schema. Falls back to treating the entire response
        as a user message if parsing fails.
        """
        json_str = None

        try:
            # Try to find JSON code block
            if '```json' in text:
                block_start = text.find('```json')
                end = text.find('```', block_start + 7)
                if end > block_start:
                    json_str = text[block_start + 7:end].strip()

            # Try to find inline JSON object
            elif text.strip().startswith('{'):
                # Find matching closing brace
                brace_count = 0
                start = text.find('{')
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

            if json_str:
                data = json.loads(json_str)
                return AgentResponse.model_validate(data)

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from response: {e}")
        except ValidationError as e:
            logger.warning(f"Response validation failed: {e}")

        # Fallback: treat the entire response as a user message
        logger.warning("Falling back to treating response as plain user message")
        return AgentResponse(user_message=text)

    def _build_tool_result_message(self, tool_name: str, result: MCPToolResult) -> list:
        """Build a multimodal message from tool result for Gemini."""
        parts: list[str | GenaiPart] = []

        # Add text description
        if result.error:
            parts.append(f"Tool '{tool_name}' failed with error: {result.error}")
        else:
            text_content = result.get_text()
            if text_content:
                parts.append(f"Tool '{tool_name}' executed. Result:\n```\n{text_content}\n```")
            else:
                parts.append(f"Tool '{tool_name}' executed successfully.")

        # Add images using protos.Part with inline_data dict
        for image in result.images:
            image_part = genai.protos.Part(
                inline_data={"mime_type": image.mime_type, "data": image.data}
            )
            parts.append(image_part)
            logger.info(f"Adding image to message: {image.mime_type}, {len(image.data)} bytes")

        # Add instruction for model (remind to use structured format)
        if result.has_images():
            parts.append(TOOL_RESULT_REMINDER_WITH_IMAGE)
        else:
            parts.append(TOOL_RESULT_REMINDER)

        return parts

    def _dump_context(self, trigger: str) -> None:
        """Dump the current chat context to a JSON file for debugging.

        Args:
            trigger: Description of what triggered the dump (e.g., "after_message")
        """
        if not LOGS_DIR.exists():
            LOGS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = LOGS_DIR / f"context_{timestamp}_{trigger}.json"

        # Stats counters
        total_messages = 0
        total_chars = 0
        total_images = 0

        # Serialize the chat history
        history: list[dict] = []

        if self.chat and hasattr(self.chat, "history"):
            for msg in self.chat.history:
                serialized_parts: list[dict] = []
                role = msg.role if hasattr(msg, "role") else "unknown"

                parts = msg.parts if hasattr(msg, "parts") else []
                for part in parts:
                    if hasattr(part, "text"):
                        # Text part
                        text = part.text
                        serialized_parts.append({
                            "type": "text",
                            "content": text,
                            "char_count": len(text),
                        })
                        total_chars += len(text)
                    elif hasattr(part, "inline_data"):
                        # Image/binary part
                        size = 0
                        if hasattr(part.inline_data, "data"):
                            size = len(part.inline_data.data)
                        serialized_parts.append({
                            "type": "image",
                            "mime_type": getattr(part.inline_data, "mime_type", "unknown"),
                            "size_bytes": size,
                        })
                        total_images += 1
                    else:
                        # Unknown part type
                        serialized_parts.append({
                            "type": "unknown",
                            "repr": str(part)[:200],
                        })

                history.append({"role": role, "parts": serialized_parts})
                total_messages += 1

        context_data = {
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "history": history,
            "stats": {
                "total_messages": total_messages,
                "total_chars": total_chars,
                "total_images": total_images,
            },
        }

        # Write to file
        with open(filename, "w") as f:
            json.dump(context_data, f, indent=2, default=str)

        logger.info(
            f"Context dumped to {filename} "
            f"(messages={total_messages}, "
            f"chars={total_chars}, "
            f"images={total_images})"
        )

    async def process_message(self, user_message: str) -> str:
        """Process a user message and return a response.

        Uses an agentic loop that continues executing tools until the LLM
        responds without a tool call, or max iterations is reached.

        Only user_message fields from the structured response are returned
        to the user. Thinking is logged internally, and tool calls are
        executed silently.
        """
        if self.chat is None:
            raise RuntimeError("Agent not initialized. Call initialize() first.")

        try:
            # Send initial message to Gemini
            response = await self.chat.send_message_async(user_message)
            response_text = response.text

            # Collect user messages to return at the end
            user_messages: list[str] = []

            # Agentic loop: keep executing tools until LLM stops requesting them
            iterations = 0
            while iterations < MAX_ITERATIONS:
                # Parse the structured response
                parsed = self._parse_response(response_text)

                # Log thinking (internal, not shown to user)
                if parsed.thinking:
                    logger.info(f"Agent thinking: {parsed.thinking}")

                # Collect any user message
                if parsed.user_message:
                    user_messages.append(parsed.user_message)

                # Check if there's a tool call to execute
                if not parsed.tool_call:
                    # No tool call - we're done, return collected messages
                    break

                iterations += 1
                tool_name = parsed.tool_call.name
                arguments = parsed.tool_call.arguments
                logger.info(
                    f"Iteration {iterations}/{MAX_ITERATIONS}: "
                    f"Executing tool: {tool_name} with args: {arguments}"
                )

                # Execute the tool
                result = await self._execute_tool(tool_name, arguments)
                result_text = result.get_text()
                logger.info(
                    f"Tool result: {result_text[:500] if result_text else 'No text'}..."
                )

                if result.has_images():
                    logger.info(f"Tool returned {len(result.images)} image(s)")

                # Build multimodal message with tool result (includes errors)
                follow_up_parts = self._build_tool_result_message(tool_name, result)

                # Send result to Gemini and get next response
                response = await self.chat.send_message_async(follow_up_parts)
                response_text = response.text

                # Dump context after each tool execution for debugging
                self._dump_context(f"after_tool_{tool_name}_iter{iterations}")

            else:
                # Max iterations reached (while loop completed without break)
                logger.warning(f"Max iterations ({MAX_ITERATIONS}) reached")
                self._dump_context("max_iterations_reached")
                user_messages.append(
                    "I've reached the maximum number of actions I can take for this "
                    "request. Please try a simpler request or provide more specific "
                    "instructions."
                )

            # Dump final context
            self._dump_context("end_of_message")

            # Return collected user messages (or a default if none)
            if user_messages:
                return "\n\n".join(user_messages)
            return "Task completed."

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            # Dump context on error for debugging
            self._dump_context(f"error_{type(e).__name__}")
            raise

    async def cleanup(self):
        """Cleanup resources."""
        if self.mcp_client:
            await self.mcp_client.disconnect()
