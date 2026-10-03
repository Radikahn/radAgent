"""
The chats the clients work with, shared by every device connected to this server

Clients connect and leave (radagent.server.ws); the chats, their agents and the turns running in them stay. A reply
keeps streaming, and saving, when the phone that asked goes to sleep, and every connected device sees it
"""
import asyncio
import base64
import binascii
import functools
import re
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from radagent.agent import RadAgent
from radagent.cards import is_card
from radagent.chats import ChatStore
from radagent.commands import COMMANDS, Command, CommandRun
from radagent.media import Attachment, MediaError
from radagent.server.history import describe, to_turns
from radagent.storage import StorageUnavailable

# How long saving memory may take when the server shuts down before it gives up on it
SHUTDOWN_TIMEOUT_S: int = 30
# Turn ids are the client's crypto.randomUUID(); a command's turn keeps its id in the saved conversation
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

Send = Callable[..., None]



class Client(Protocol):
    """One connected device"""

    # The chat on its screen, whose agent stays loaded
    viewing: str | None

    def send(self, kind: str, **fields: Any) -> None:
        """Queue an event for this device; called on the server's event loop"""
        ...



class Hub:
    """
    The connected clients; events about chats go to all of them, so a turn started on one device streams on the others

    send() may be called from any thread (tools emit from their own), and hops onto the server's loop
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.clients: set[Client] = set()


    def join(self, client: Client) -> None:
        self.clients.add(client)


    def leave(self, client: Client) -> None:
        self.clients.discard(client)


    def viewing(self) -> set[str]:
        """The chats on any device's screen"""
        return {client.viewing for client in self.clients if client.viewing}


    def send(self, kind: str, **fields: Any) -> None:
        try:
            on_loop = asyncio.get_running_loop() is self.loop
        except RuntimeError:
            on_loop = False
        if not on_loop:
            self.loop.call_soon_threadsafe(functools.partial(self.send, kind, **fields))
            return
        for client in list(self.clients):
            client.send(kind, **fields)



def _forward(event: dict[str, Any], send: Send) -> None:
    """Send the parts of one Strands stream event that the client renders"""
    if text := event.get("data"):
        send("text", delta = text)
    if reasoning := event.get("reasoningText"):
        send("thinking", delta = reasoning)

    chunk = event.get("event")
    tool_use = chunk.get("contentBlockStart", {}).get("start", {}).get("toolUse") if isinstance(chunk, dict) else None
    if tool_use:
        send("tool_start", id = tool_use["toolUseId"], name = tool_use["name"])

    # Finished messages carry each call's full input (assistant) and its outcome (the tool results message)
    message = event.get("message")
    for block in message.get("content", []) if isinstance(message, dict) else []:
        if "toolUse" in block:
            send("tool_input", id = block["toolUse"]["toolUseId"], detail = describe(block["toolUse"].get("input")))
        elif "toolResult" in block:
            send("tool_end", id = block["toolResult"]["toolUseId"], status = block["toolResult"].get("status", "success"))

    # Tools yield cards as stream events, kept apart from the result the model sees; see radagent.cards
    tool_stream = event.get("tool_stream_event")
    if isinstance(tool_stream, dict) and is_card(tool_stream.get("data")):
        send("card", id = tool_stream["tool_use"]["toolUseId"], card = tool_stream["data"])

    if event.get("force_stop"):
        send("error", message = event.get("force_stop_reason") or "The agent stopped unexpectedly")


def silent(**_: Any) -> None:
    """Callback handler that drops everything; the stream goes to the clients instead of the terminal"""


def _decode_attachments(items: Any) -> list[Attachment]:
    """The files a prompt command carries, each {"name": str, "data": base64 str}"""
    attachments: list[Attachment] = []
    for item in items:
        name = str(item.get("name") or "file") if isinstance(item, dict) else "file"
        try:
            attachments.append(Attachment(name = name, data = base64.b64decode(item["data"], validate = True)))
        except (KeyError, TypeError, binascii.Error):
            raise MediaError(f"{name} arrived unreadable") from None
    return attachments


async def _run_turn(agent: RadAgent, prompt: str, command: str | None, attachments: list[Attachment], send: Send) -> None:
    stop_reason = "error"
    try:
        stream = agent.stream(prompt, cross_chat = command == "memory", attachments = attachments, code = command == "code")
        async for event in stream:
            _forward(event, send)
            if "result" in event:
                stop_reason = event["result"].stop_reason
    except MediaError as e:
        # Raised before anything reaches the model, so the user can fix the files and send again
        send("error", message = str(e))
        stop_reason = "rejected"
    except Exception as e:
        send("error", message = f"{type(e).__name__}: {e}")
    finally:
        send("turn_end", stop_reason = stop_reason)


async def _retire(agent: RadAgent) -> None:
    """Let a finished agent save what it learned; a failure only loses this conversation's memories"""
    try:
        await agent.close()
    except Exception as e:
        print(f"[radagent] saving memory failed: {type(e).__name__}: {e}", file = sys.stderr)



class Chats:
    """
    The chats the clients work with: an agent for each one that's loaded, and the turns running in them

    A chat's agent loads with its first message after the chat is opened and unloads, saving its memory, once no
    device has it on screen and it has finished answering. So a reply keeps streaming in the background while the
    user reads or writes elsewhere, or puts the phone away
    """

    def __init__(self, hub: Hub, store: ChatStore, new_agent: Callable[[str], RadAgent]) -> None:
        self.hub = hub
        self.store = store
        self.new_agent = new_agent
        self.agents: dict[str, RadAgent] = {}
        self.turns: dict[str, asyncio.Task[None]] = {}
        # Chats whose running turn is a slash command rather than the agent answering
        self.commands: set[str] = set()
        # Agents saving their memory after unloading, and chats being deleted, which wait for those to finish
        self.closing: dict[str, asyncio.Task[None]] = {}
        self.deleting: dict[str, asyncio.Task[None]] = {}


    def busy(self, chat_id: str) -> bool:
        turn = self.turns.get(chat_id)
        return turn is not None and not turn.done()


    def working(self) -> bool:
        """Whether anything is running that a shutdown would cut short: a turn, or memory being saved"""
        return any(self.busy(chat_id) for chat_id in self.turns) or bool(self.closing) or bool(self.deleting)


    def send_list(self, to: Client | Hub | None = None) -> None:
        """The chats, to one client or, by default, to all of them"""
        to = to or self.hub
        try:
            to.send("chats", chats = self.store.recent())
        except StorageUnavailable as e:
            to.send("error", message = str(e))


    def open(self, chat_id: str, client: Client) -> None:
        client.viewing = chat_id
        self.unload_idle()
        try:
            turns = to_turns(self.store.messages(chat_id), self.store.cards(chat_id))
        except StorageUnavailable as e:
            # Without a history event the client asks again the next time the chat is opened
            client.send("error", message = str(e))
            return
        client.send("history", chat = chat_id, turns = turns, running = self.busy(chat_id))


    def prompt(self, chat_id: str, turn_id: Any, text: str, command: Any, attachments: Any, client: Client) -> None:
        send = functools.partial(self.hub.send, chat = chat_id, turn = turn_id)
        if chat_id in self.deleting:
            send("error", message = "This chat was deleted")
            send("turn_end", stop_reason = "rejected")
        elif self.busy(chat_id):
            send("error", message = "Still answering the last message")
            send("turn_end", stop_reason = "rejected")
        elif not text and not attachments:
            send("turn_end", stop_reason = "rejected")
        else:
            try:
                files = _decode_attachments(attachments)
            except MediaError as e:
                send("error", message = str(e))
                send("turn_end", stop_reason = "rejected")
                return
            client.viewing = chat_id
            # A chat appears in the list with its first message, titled after it (or its files when it has no text)
            try:
                self.store.touch(chat_id, first_message = text or ", ".join(file.name for file in files))
            except StorageUnavailable as e:
                # The agent couldn't load or save the chat either
                send("error", message = str(e))
                send("turn_end", stop_reason = "rejected")
                return
            # The other devices learn of the turn here; the one that sent it already shows it
            send("turn_start", text = text, command = command if isinstance(command, str) else None,
                 attachments = [file.name for file in files])
            self.send_list()
            if slash := COMMANDS.get(command) if isinstance(command, str) else None:
                task = self._run_command(chat_id, turn_id, slash, text, send)
            else:
                task = self._answer(chat_id, text, command if isinstance(command, str) else None, files, send)
            self.turns[chat_id] = asyncio.create_task(task)


    async def _load(self, chat_id: str, send: Send) -> RadAgent | None:
        """The chat's agent, started if it isn't loaded; None, with the turn ended, when it can't start"""
        agent = self.agents.get(chat_id)
        if agent is None:
            # The agent that last had this chat may still be saving its memory; let it finish first
            if closing := self.closing.get(chat_id):
                await closing
            try:
                agent = self.agents[chat_id] = self.new_agent(chat_id)
            except Exception as e:
                send("error", message = f"Could not start the agent: {type(e).__name__}: {e}")
                send("turn_end", stop_reason = "error")
                return None
        return agent


    def _finish(self, chat_id: str) -> None:
        if chat_id not in self.deleting:
            try:
                self.store.touch(chat_id)
            except StorageUnavailable as e:
                self.hub.send("error", message = str(e))
            self.send_list()
        self.unload_idle(finished = chat_id)


    async def _answer(self, chat_id: str, text: str, command: str | None, attachments: list[Attachment], send: Send) -> None:
        if (agent := await self._load(chat_id, send)) is None:
            return

        def send_and_keep(kind: str, **fields: Any) -> None:
            # Cards stream to the clients outside the saved conversation, so the chat keeps its own copy
            if kind == "card":
                self.store.add_card(chat_id, fields["id"], fields["card"])
            send(kind, **fields)

        await _run_turn(agent, text, command, attachments, send_and_keep)
        self._finish(chat_id)


    async def _run_command(self, chat_id: str, turn_id: Any, command: Command, text: str, send: Send) -> None:
        """
        Run a slash command such as /research, streaming its progress as `command_event`s

        Its events are kept, trimmed, beside the chat's cards under "command:<turn id>", so a reopened chat shows the
        turn the way it ended rather than as the plain text recorded in the conversation
        """
        if (agent := await self._load(chat_id, send)) is None:
            return
        self.commands.add(chat_id)
        started = time.monotonic()
        timeline: list[tuple[float, Any]] = []
        lock = threading.Lock()

        def emit(event: Any) -> None:
            # Research agents emit from their own threads as well as this loop
            with lock:
                timeline.append((time.monotonic() - started, event))
            send("command_event", command = command.name, event = event)

        turn = turn_id if isinstance(turn_id, str) and _UUID.fullmatch(turn_id) else None
        stop_reason = "end_turn"
        try:
            await command.run(CommandRun(agent, text, emit, turn))
        except asyncio.CancelledError:
            # Stopped from a client; the task ends normally so whoever is waiting on it carries on
            stop_reason = "cancelled"
        except Exception as e:
            stop_reason = "error"
            send("error", message = str(e) or type(e).__name__)
        finally:
            self.commands.discard(chat_id)
            if turn and timeline and chat_id not in self.deleting:
                try:
                    self.store.add_card(chat_id, f"command:{turn}", {"command": command.name, "events": command.keep(timeline)})
                except StorageUnavailable as e:
                    # The turn still ends; only a reopened chat loses the replay and shows the recorded reply instead
                    send("error", message = str(e))
            send("turn_end", stop_reason = stop_reason)
        self._finish(chat_id)


    def cancel(self, chat_id: str) -> None:
        if not self.busy(chat_id):
            return
        if chat_id in self.commands:
            # A command drives its own agents, so stopping it means stopping its task
            self.turns[chat_id].cancel()
        elif agent := self.agents.get(chat_id):
            agent.cancel()


    def leave(self, client: Client) -> None:
        """A device disconnected; what it started keeps running, and the chat it showed may now unload"""
        self.hub.leave(client)
        self.unload_idle()


    def unload_idle(self, finished: str | None = None) -> None:
        """
        Unload the agents of chats no device has on screen that aren't answering

        Args:
            finished: {str | None} A chat whose turn is ending; its task is still running while it calls this
        """
        viewing = self.hub.viewing()
        for chat_id in list(self.agents):
            if chat_id in viewing or chat_id in self.deleting or (self.busy(chat_id) and chat_id != finished):
                continue
            task = self.closing[chat_id] = asyncio.create_task(_retire(self.agents.pop(chat_id)))
            task.add_done_callback(functools.partial(self._closed, chat_id))


    def _closed(self, chat_id: str, task: asyncio.Task[None]) -> None:
        # The chat may have loaded and unloaded again since, leaving a newer task under its id
        if self.closing.get(chat_id) is task:
            del self.closing[chat_id]


    def delete(self, chat_id: str) -> None:
        # The chat leaves the list at once; its folder goes once nothing can write to it any more
        try:
            self.store.forget(chat_id)
        except StorageUnavailable as e:
            # It's still on the list, so deleting it again tries again
            self.hub.send("error", message = str(e))
            return
        self.send_list()
        for client in self.hub.clients:
            if client.viewing == chat_id:
                client.viewing = None
        if chat_id not in self.deleting:
            task = self.deleting[chat_id] = asyncio.create_task(self._delete(chat_id))
            task.add_done_callback(lambda _: self.deleting.pop(chat_id, None))


    async def _delete(self, chat_id: str) -> None:
        if self.busy(chat_id):
            self.cancel(chat_id)
            await self.turns[chat_id]
        # Saving memory writes into the chat's folder, so it has to finish before the folder is removed
        if agent := self.agents.pop(chat_id, None):
            await _retire(agent)
        if closing := self.closing.get(chat_id):
            await closing
        try:
            self.store.delete(chat_id)
        except StorageUnavailable as e:
            # chat.json is already gone, so the chat stays off the list; the rest of its files are left behind
            self.hub.send("error", message = f"The chat's files weren't all removed: {e}")


    async def close(self) -> None:
        """Stop what's running and let every agent save its memory"""
        for chat_id in self.agents:
            self.cancel(chat_id)
        await asyncio.gather(*self.turns.values())
        await asyncio.gather(
            *(_retire(agent) for agent in self.agents.values()), *self.closing.values(), *self.deleting.values()
        )



def dispatch(chats: Chats, client: Client, command: Any) -> None:
    """
    Carry out one command from a client

    Commands, each naming the chat it's for (ids come from the client):
        {"type": "list"}                                    the chats, as a `chats` event
        {"type": "open", "chat": id}                        the chat's saved turns, as a `history` event
        {"type": "prompt", "chat": id, "turn": id, "text": str, "command": "memory" | "code" | "research" | None,
         "attachments"?: [{"name": str, "data": base64}]}
        {"type": "cancel", "chat": id}
        {"type": "delete", "chat": id}
    A chat that has never had a message has nothing saved; its first prompt creates it. "command": "memory" is
    /memory, which lets that one message look through the other chats, and "code" is /code, which asks for code
    in copyable code blocks (radagent.coding); any command in radagent.commands, such as "research", runs that
    command on the text instead of the agent answering it. Attachments are images, PDFs, Office and text files;
    a prompt may carry them without text

    Events out: ready, chats, history (to the client that opened the chat), error, and per turn turn_start, text,
    thinking, tool_start, tool_input, tool_end, card, command_event ({"command": name, "event": ...}, the command's
    own progress) and turn_end, each carrying the `chat` and `turn` it belongs to, to every client
    """
    if not isinstance(command, dict):
        client.send("error", message = "Commands are JSON objects")
        return

    kind = command.get("type")
    given = command.get("chat")
    chat_id = given if chats.store.valid_id(given) else ""
    if kind in ("open", "prompt", "cancel", "delete") and not chat_id:
        client.send("error", message = f"{kind} needs a chat id, got {given!r}", turn = command.get("turn"))
        return

    match kind:
        case "list":
            chats.send_list(client)
        case "open":
            chats.open(chat_id, client)
        case "prompt":
            text = str(command.get("text") or "").strip()
            chats.prompt(chat_id, command.get("turn"), text, command.get("command"), command.get("attachments") or [], client)
        case "cancel":
            chats.cancel(chat_id)
        case "delete":
            chats.delete(chat_id)
        case other:
            client.send("error", message = f"Unknown command {other!r}")
