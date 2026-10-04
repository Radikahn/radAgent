"""
Slash commands: work the user starts directly, like `/research <topic>`, instead of asking the agent for it

A command runs outside the agent's own loop, so it can drive its own crew of agents and stream its own progress
events. When it ends, the exchange is recorded in the conversation as if the agent had answered, so the user can
follow up on it in plain chat. The desktop client sends the command's name with the prompt; the REPL types it
"""
import asyncio
import uuid
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import Any

from strands.hooks import MessageAddedEvent
from strands.types.content import Message

from radagent.agent import RadAgent
from radagent.config import PROFILE_MODEL, RESEARCH_AGENT_MODEL, RESEARCH_MODEL
from radagent.profile import profile_store
from radagent.tools.research import for_replay, run_research


# Receives the command's progress events; each command defines its own (see tools/research/events.py)
Emit = Callable[[Any], None]


@dataclass(frozen = True)
class CommandRun:
    agent: RadAgent             # The conversation the command runs in
    arguments: str              # What the user typed after the command's name
    emit: Emit
    turn_id: str | None = None  # A UUID naming this turn; a saved chat finds the turn's replay by it


@dataclass(frozen = True)
class Command:
    name: str
    usage: str                  # What follows the name, e.g. "<topic>"
    description: str
    # Runs the command and returns the Markdown reply recorded in the conversation
    run: Callable[[CommandRun], Coroutine[Any, Any, str]]
    # Trims a run's timed events to what a saved chat keeps to show it again
    keep: Callable[[list[tuple[float, Any]]], list[dict[str, Any]]] = lambda timeline: []
    # The command emits no events of its own; its reply streams to the client the way the agent's text does
    reply_as_text: bool = False



async def remember(agent: RadAgent, prompt: str, reply: str, urls: Iterable[str] = (), turn_id: str | None = None) -> None:
    """
    Record an exchange that happened outside the agent's loop, so the conversation (and its saved session) has it

    Args:
        agent: {RadAgent}
        prompt: {str} What the user asked, as they typed it
        reply: {str} The answer to show the model as its own
        urls: {Iterable[str]} Web pages the reply was drawn from; they gate shell, write and edit like a page read
        turn_id: {str | None} A UUID for the prompt's message, so a saved chat rebuilds the turn under this id
    """
    strands_agent = agent.AGENT
    asked: Message = {"role": "user", "content": [{"text": prompt}], "tracking_id": turn_id or str(uuid.uuid4())}
    answered: Message = {"role": "assistant", "content": [{"text": reply}], "tracking_id": str(uuid.uuid4())}
    messages = [asked, answered]
    # The history must alternate; a turn that failed before replying leaves the user's message last
    if strands_agent.messages and strands_agent.messages[-1]["role"] == "user":
        messages.insert(0, {"role": "assistant", "content": [{"text": "(No reply.)"}], "tracking_id": str(uuid.uuid4())})

    for message in messages:
        strands_agent.messages.append(message)
        # What the agent's own loop does for each message, which is how the session manager saves it
        await strands_agent.hooks.invoke_callbacks_async(MessageAddedEvent(agent = strands_agent, message = message))
    agent.trust_gate.record_content(strands_agent, urls)



async def _research(run: CommandRun) -> str:
    topic = run.arguments
    if not topic:
        raise ValueError("Say what to research, e.g. /research solid-state battery timelines")
    prompt = f"/research {topic}"
    try:
        report = await run_research(
            topic,
            model = RESEARCH_MODEL or run.agent.model,
            agent_model = RESEARCH_AGENT_MODEL or run.agent.model,
            emit = run.emit,
        )
    except asyncio.CancelledError:
        # Keep the turn in the conversation, so the chat shows it and the agent knows it was asked
        await remember(run.agent, prompt, "The research was stopped before the report was written.", turn_id = run.turn_id)
        raise
    except Exception as e:
        await remember(run.agent, prompt, f"The research failed: {e}", turn_id = run.turn_id)
        raise

    reply = report.markdown()
    await remember(run.agent, prompt, reply, [source["url"] for source in report.sources], run.turn_id)
    return reply


async def _profile(run: CommandRun) -> str:
    note = run.arguments
    store = profile_store()
    if not note:
        # On its own, /profile shows what's on it
        markdown = await asyncio.to_thread(store.current)
        reply = (
            f"{markdown}\n\n*Every chat knows this. Add to it or correct it with /profile.*" if markdown
            else "Your profile is empty. Start a message with /profile to add to it, e.g. `/profile I'm a nurse in "
                 "Toronto and I have a dog named Miso`. Every chat knows what's on it."
        )
        await remember(run.agent, "/profile", reply, turn_id = run.turn_id)
        return reply

    prompt = f"/profile {note}"
    try:
        summary, _ = await store.add(note, model = PROFILE_MODEL or run.agent.model, chat = run.agent.chat_id)
    except asyncio.CancelledError:
        await remember(run.agent, prompt, "Stopped before the profile took this in; the note is kept and goes in "
                                          "with the next /profile.", turn_id = run.turn_id)
        raise
    except Exception as e:
        await remember(run.agent, prompt, f"Adding that to the profile failed: {e}", turn_id = run.turn_id)
        raise

    reply = f"{summary}\n\n*Every chat knows this now. Send /profile on its own to see your whole profile.*"
    await remember(run.agent, prompt, reply, turn_id = run.turn_id)
    return reply


COMMANDS: dict[str, Command] = {
    command.name: command
    for command in (
        Command(
            name = "research",
            usage = "<topic>",
            description = "Send a crew of agents across the web and get back a cited report",
            run = _research,
            keep = for_replay,
        ),
        Command(
            name = "profile",
            usage = "[something about you]",
            description = "Add to the profile every chat knows you by; on its own, show it",
            run = _profile,
            reply_as_text = True,
        ),
    )
}



def parse_command(text: str) -> tuple[Command, str] | None:
    """
    Split typed text like "/research heat pumps" into its command and arguments

    Returns:
        (command, arguments): {tuple[Command, str] | None} None when the text doesn't start with a known command
    """
    words = text[1:].split(maxsplit = 1) if text.startswith("/") else []
    command = COMMANDS.get(words[0].lower()) if words else None
    if command is None:
        return None
    return command, words[1].strip() if len(words) > 1 else ""
