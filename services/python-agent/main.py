import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent import BrowserAgent

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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connection_id = str(id(websocket))

    # Create agent for this connection
    agent = BrowserAgent()
    await agent.initialize()
    active_connections[connection_id] = (websocket, agent)

    logger.info(f"Client connected: {connection_id}")

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
                    "recording": is_recording
                })

            elif message.get("type") == "message":
                user_content = message.get("content", "")
                logger.info(f"Received message: {user_content}")

                # Send status update
                await websocket.send_json({
                    "type": "status",
                    "content": "thinking"
                })

                # Process with agent
                try:
                    response, demo_metadata = await agent.process_message(user_content)
                    response_data: dict = {
                        "type": "response",
                        "content": response
                    }
                    if demo_metadata:
                        response_data["demo_metadata"] = demo_metadata
                    await websocket.send_json(response_data)
                except Exception as e:
                    logger.error(f"Agent error: {e}")
                    await websocket.send_json({
                        "type": "response",
                        "content": f"Sorry, I encountered an error: {str(e)}"
                    })

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cleanup
        if connection_id in active_connections:
            _, agent = active_connections[connection_id]
            await agent.cleanup()
            del active_connections[connection_id]


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
