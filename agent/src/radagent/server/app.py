"""
The agent as a service: the HTTP contract AgentCore Runtime expects, on port 8080

    /ws            the clients' WebSocket (radagent.server.ws); AgentCore checks the Cognito token before it gets here
    /ping          Healthy, or HealthyBusy while a turn or a memory save is running, so AgentCore doesn't stop the
                   session under it when every device has disconnected
    /invocations   a status check, for smoke tests; the agent itself is only reachable over the WebSocket

Run it locally with `uv run radagent --serve --port 8787` (the apps' development builds expect 8787); it then listens on
127.0.0.1 with no authentication
"""
import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp, PingStatus
from starlette.websockets import WebSocket

from radagent.agent import RadAgent
from radagent.chats import ChatStore
from radagent.server.core import SHUTDOWN_TIMEOUT_S, Chats, Hub, silent
from radagent.server.ws import serve



def create_app(model: str | None = None, system_prompt: str | None = None) -> BedrockAgentCoreApp:
    """
    Args:
        model: {str | None} Override the default model defined in `config.py`
        system_prompt: {str | None} Override the default system prompt
    """
    store = ChatStore()
    chats: Chats | None = None

    def new_agent(chat_id: str) -> RadAgent:
        kwargs: dict[str, Any] = {"model": model, "callback_handler": silent, "chat_id": chat_id, "chats": store}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        return RadAgent(**kwargs)

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        # The chats need the server's event loop, which only exists once it starts
        nonlocal chats
        chats = Chats(Hub(asyncio.get_running_loop()), store, new_agent)
        yield
        try:
            await asyncio.wait_for(chats.close(), SHUTDOWN_TIMEOUT_S)
        except TimeoutError:
            print("[radagent] gave up saving memory on shutdown", file = sys.stderr)

    app = BedrockAgentCoreApp(lifespan = lifespan)

    @app.websocket
    async def connect(websocket: WebSocket, _context: Any) -> None:
        assert chats is not None, "connections only arrive once the server has started"
        await serve(websocket, chats)

    @app.ping
    def ping() -> PingStatus:
        return PingStatus.HEALTHY_BUSY if chats is not None and chats.working() else PingStatus.HEALTHY

    @app.entrypoint
    def status(_payload: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "websocket": "/ws",
            "connected": len(chats.hub.clients) if chats else 0,
            "working": bool(chats and chats.working()),
        }

    return app


def run_server(model: str | None = None, system_prompt: str | None = None, host: str | None = None, port: int = 8080) -> None:
    """
    Serve the clients until the process is stopped

    Args:
        model: {str | None} Override the default model defined in `config.py`
        system_prompt: {str | None} Override the default system prompt
        host: {str | None} Where to listen; None is 127.0.0.1, or 0.0.0.0 inside a container
        port: {int}
    """
    create_app(model, system_prompt).run(port = port, host = host)
