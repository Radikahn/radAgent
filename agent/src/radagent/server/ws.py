"""
The WebSocket a client connects over, framed to fit AgentCore Runtime's limits

AgentCore caps a WebSocket frame at 64 KB and a connection at 250 frames a second, so
    - events are queued per connection and sent together, as one JSON array, every FLUSH_S
    - a message that would be larger than FRAME_LIMIT goes as parts instead:
          {"type": "part", "id": str, "n": 0-based index, "of": count, "data": a slice of the message's JSON}
      and the receiver joins the data in order and parses it. Clients send large commands (attachments) the same way
A connection lasts at most an hour there, so clients reconnect; nothing about a chat lives in the connection
"""
import asyncio
import json
import sys
import uuid
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from radagent.server.core import Chats, dispatch

# How long events wait to be sent together; short enough that text still reads as streaming
FLUSH_S: float = 0.04
# The most a message may carry before it's sent in parts, in bytes; under AgentCore's 64 KB frame limit
FRAME_LIMIT: int = 48 * 1024
# Characters of a large message per part. Messages are ASCII (ensure_ascii), and quoting a slice inside a part's
# JSON at most doubles it, so a part stays under FRAME_LIMIT
PART_CHARS: int = 24 * 1024
# A client's command, joined from parts, can't be larger than this; attachments are capped at 25 MB each client-side
MAX_COMMAND_BYTES: int = 40 * 1024 * 1024
# The subprotocol a browser offers to carry its token (the token rides in a second, unique one); AgentCore checks
# the token before the connection reaches us, and the handshake has to pick one of the offered protocols back
BEARER_PROTOCOL: str = "base64UrlBearerAuthorization"



def _encode(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii = True, default = str, separators = (",", ":"))


def frames(events: list[dict[str, Any]]) -> list[str]:
    """
    The messages that carry `events`, in order: arrays of events up to FRAME_LIMIT, and parts for an event larger
    than that on its own
    """
    messages: list[str] = []
    batch: list[str] = []
    size = 2

    def close_batch() -> None:
        nonlocal batch, size
        if batch:
            messages.append("[" + ",".join(batch) + "]")
        batch, size = [], 2

    for event in events:
        encoded = _encode(event)
        if len(encoded) + 2 > FRAME_LIMIT:
            close_batch()
            message_id = uuid.uuid4().hex
            slices = [encoded[start:start + PART_CHARS] for start in range(0, len(encoded), PART_CHARS)]
            messages.extend(
                _encode({"type": "part", "id": message_id, "n": n, "of": len(slices), "data": data})
                for n, data in enumerate(slices)
            )
            continue
        if size + len(encoded) + 1 > FRAME_LIMIT:
            close_batch()
        batch.append(encoded)
        size += len(encoded) + 1
    close_batch()
    return messages



class _Parts:
    """Joins a client's messages that arrived in parts"""

    def __init__(self) -> None:
        self.pending: dict[str, list[str | None]] = {}
        self.sizes: dict[str, int] = {}


    def add(self, part: dict[str, Any]) -> str | None:
        """The whole message once its last part is in, otherwise None"""
        message_id, n, of, data = part.get("id"), part.get("n"), part.get("of"), part.get("data")
        if not (isinstance(message_id, str) and isinstance(n, int) and isinstance(of, int) and isinstance(data, str)):
            raise ValueError("a part needs id, n, of and data")
        if not 0 <= n < of:
            raise ValueError(f"part {n} of {of}")
        slices = self.pending.setdefault(message_id, [None] * of)
        if len(slices) != of:
            raise ValueError("a message's parts disagree on how many there are")
        size = self.sizes[message_id] = self.sizes.get(message_id, 0) + len(data)
        if size > MAX_COMMAND_BYTES:
            self.pending.pop(message_id)
            self.sizes.pop(message_id)
            raise ValueError("message too large")
        slices[n] = data
        if any(piece is None for piece in slices):
            return None
        self.pending.pop(message_id)
        self.sizes.pop(message_id)
        return "".join(slices)  # type: ignore[arg-type]



class Connection:
    """One connected client: what it has on screen and the events waiting to be sent to it"""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.viewing: str | None = None
        self.loop = asyncio.get_running_loop()
        self.pending: list[dict[str, Any]] = []
        self.outbox: asyncio.Queue[str | None] = asyncio.Queue()
        self.flush_handle: asyncio.TimerHandle | None = None
        self.closed = False


    def send(self, kind: str, **fields: Any) -> None:
        if self.closed:
            return
        self.pending.append({"type": kind, **fields})
        if self.flush_handle is None:
            self.flush_handle = self.loop.call_later(FLUSH_S, self.flush)


    def flush(self) -> None:
        self.flush_handle = None
        events, self.pending = self.pending, []
        for message in frames(events):
            self.outbox.put_nowait(message)


    async def write(self) -> None:
        """Send queued messages in order until the connection closes"""
        try:
            while (message := await self.outbox.get()) is not None:
                await self.websocket.send_text(message)
        except (WebSocketDisconnect, RuntimeError, OSError):
            # The client went away mid-send; the reader sees it too and cleans up
            self.closed = True


    def close(self) -> None:
        self.closed = True
        if self.flush_handle is not None:
            self.flush_handle.cancel()
            self.flush_handle = None
        self.outbox.put_nowait(None)



async def serve(websocket: WebSocket, chats: Chats) -> None:
    """Serve one client until it disconnects; what it started keeps running"""
    offered = websocket.scope.get("subprotocols") or []
    await websocket.accept(subprotocol = BEARER_PROTOCOL if BEARER_PROTOCOL in offered else None)

    connection = Connection(websocket)
    writer = asyncio.create_task(connection.write())
    parts = _Parts()
    chats.hub.join(connection)
    connection.send("ready")
    chats.send_list(connection)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            text = message.get("text")
            if text is None and (data := message.get("bytes")) is not None:
                text = data.decode("utf-8", errors = "replace")
            if not text:
                continue
            try:
                command = json.loads(text)
                if isinstance(command, dict) and command.get("type") == "part":
                    if (whole := parts.add(command)) is None:
                        continue
                    command = json.loads(whole)
            except ValueError as e:
                connection.send("error", message = f"Unreadable command: {e}")
                continue
            dispatch(chats, connection, command)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[radagent] connection failed: {type(e).__name__}: {e}", file = sys.stderr)
    finally:
        chats.leave(connection)
        connection.close()
        await writer
