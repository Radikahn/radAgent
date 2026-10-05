"""
Rebuilds a saved chat as the turns the client renders, so a reopened chat looks the way it did

Keep the shapes in step with `Turn` and `Part` in `client/src/agent.ts`. The saved conversation has no timings,
so thinking and tool parts carry 0 for both ends and the client shows them without durations
"""
import re
from collections.abc import Callable
from typing import Any

from radagent.clock import is_time_note
from radagent.coding import is_code_note
from radagent.commands import COMMANDS
from radagent.media import split_attachments
from radagent.tools.chats import is_cross_chat_note

# Tool inputs are cut to this length; the client only shows a one-line hint of each call
DETAIL_CHARS: int = 120
# The notes sent ahead of a message started with these commands; the turn shows the command in their place
NOTES: dict[str, Callable[[str], bool]] = {"memory": is_cross_chat_note, "code": is_code_note}
# A slash command's name at the start of a prompt the command recorded, e.g. "/profile I have a dog"
_COMMAND = re.compile(r"/(\w+)(?=\s|$)")



def describe(tool_input: Any) -> str:
    """A one-line hint of what a tool call is doing, e.g. the search query, URL or command"""
    if isinstance(tool_input, dict):
        strings = [value for value in tool_input.values() if isinstance(value, str) and value.strip()]
        tool_input = strings[0] if strings else ""
    text = " ".join(str(tool_input).split())
    return text[:DETAIL_CHARS] + "…" if len(text) > DETAIL_CHARS else text


def _note_of(text: str) -> str | None:
    """The command `text` is the note of, if it's one"""
    return next((name for name, is_note in NOTES.items() if is_note(text)), None)


def _add_text(parts: list[dict[str, Any]], kind: str, text: str) -> None:
    last = parts[-1] if parts else None
    if last is not None and last["kind"] == kind:
        last["text"] += text
    elif kind == "text":
        parts.append({"kind": "text", "text": text})
    else:
        parts.append({"kind": "thinking", "text": text, "startedAt": 0, "endedAt": 0})


def to_turns(messages: list[dict[str, Any]], cards: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Args:
        messages: {list[dict]} The chat's conversation in Strands message format
        cards: {dict[str, Any]} Cards the chat showed, by the id of the tool call that showed them, and the saved
               events of slash commands, by "command:<turn id>"

    Returns:
        turns: {list[dict]} One per message the user sent, each with the reply that followed it
    """
    turns: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    # Turns rebuilt from a command's saved events, whose recorded replies aren't shown
    replayed: set[int] = set()

    for index, message in enumerate(messages):
        content = message.get("content") or []

        if message.get("role") == "user":
            results = [block["toolResult"] for block in content if "toolResult" in block]
            # A user message carrying tool results is the harness continuing a reply, not the user speaking
            for result in results:
                if tool := tools.get(result.get("toolUseId")):
                    tool["status"] = "error" if result.get("status") == "error" else "success"
            if results:
                continue
            # Attached files come back as chips (images with a small preview) rather than as their contents
            attachments, rest = split_attachments(content)
            texts = [text for block in rest if isinstance(text := block.get("text"), str)]
            turn: dict[str, Any] = {
                "id": message.get("tracking_id") or f"saved-{index}",
                # The user's time goes ahead of every message (radagent.clock); it isn't something they wrote
                "prompt": "\n".join(text for text in texts if not _note_of(text) and not is_time_note(text)).strip(),
                "parts": [],
                "status": "done",
            }
            if notes := [name for text in texts if (name := _note_of(text))]:
                turn["command"] = notes[0]
            if attachments:
                turn["attachments"] = attachments
            # A slash command like /research saved its events under its turn; they show the turn as it ended,
            # in place of the plain reply the conversation recorded for the model
            replay = cards.get(f"command:{turn['id']}")
            if isinstance(replay, dict) and isinstance(replay.get("command"), str) and isinstance(replay.get("events"), list):
                name = replay["command"]
                turn["command"] = name
                turn["prompt"] = turn["prompt"].removeprefix(f"/{name}").strip()
                turn["parts"] = [{"kind": "command", "command": name, "events": replay["events"]}]
                replayed.add(len(turns))
            # A command with no saved events, like /profile, recorded its prompt as typed; show the command as sent
            elif "command" not in turn and (typed := _COMMAND.match(turn["prompt"])) and typed[1] in COMMANDS:
                turn["command"] = typed[1]
                turn["prompt"] = turn["prompt"][typed.end():].strip()
            turns.append(turn)
            continue

        # The context manager can leave a reply without the message that asked for it; it has nowhere to go
        if message.get("role") != "assistant" or not turns or len(turns) - 1 in replayed:
            continue
        parts = turns[-1]["parts"]
        for block in content:
            if isinstance(block.get("text"), str):
                _add_text(parts, "text", block["text"])
            elif reasoning := block.get("reasoningContent", {}).get("reasoningText", {}).get("text"):
                _add_text(parts, "thinking", reasoning)
            elif tool_use := block.get("toolUse"):
                tool = {
                    "kind": "tool",
                    "id": tool_use["toolUseId"],
                    "name": tool_use["name"],
                    "detail": describe(tool_use.get("input")),
                    "status": "success",
                    "startedAt": 0,
                    "endedAt": 0,
                }
                tools[tool["id"]] = tool
                parts.append(tool)
                if tool["id"] in cards:
                    parts.append({"kind": "card", "id": tool["id"], "card": cards[tool["id"]]})

    return turns
