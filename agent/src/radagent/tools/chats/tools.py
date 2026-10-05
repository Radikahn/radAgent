"""
Cross-chat memory: the agent can look through the user's other chats, but only for messages sent with /memory

Each chat keeps its own context and memory. These tools are registered on every desktop chat, so the tool list
(and with it the prompt cache) stays the same from turn to turn, and they refuse unless the turn's invocation
state carries the CROSS_CHAT flag, which RadAgent.stream sets only for /memory messages

A chat whose web content tainted its trust gate passes the taint on: pulling text out of it disables shell,
write and edit here too, since that text may carry the same prompt injection
"""
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, NamedTuple

from strands import ToolContext, tool

from radagent.chats import ChatInfo, ChatStore, read_legacy_memories
from radagent.clock import is_time_note
from radagent.coding import is_code_note
from radagent.tools.web.trust_gate import TAINT_STATE_KEY


# Invocation state key that unlocks these tools for one turn
CROSS_CHAT: str = "cross_chat"
# Sent ahead of a /memory message so the model knows it may use the tools; server/history.py hides it again
CROSS_CHAT_NOTE: str = (
    "<cross_chat_access>The user started this message with /memory: for this message only you may look through "
    "their other chats with you. search_chats finds facts and messages from them (leave the query empty for an "
    "overview) and read_chat reads one in full. Look before you answer.</cross_chat_access>"
)

MAX_HITS: int = 12
# Chats read at once when gathering them
SOURCE_WORKERS: int = 4
SNIPPET_CHARS: int = 280
# How much of one chat read_chat returns; the most recent part is kept
READ_CHARS: int = 12_000
OVERVIEW_CHATS: int = 15
OVERVIEW_FACTS: int = 8

_REFUSAL: str = (
    "Looking through other chats is off for this message. If the user wants you to, tell them to start their "
    "message with /memory."
)
_LEGACY_TITLE: str = "Memory from before chats"
# Words that say nothing about what to look for; a query made only of these gets the overview instead
_STOPWORDS: frozenset[str] = frozenset("""
    a about all an and any anything are as at be been but by can chat chats could did do does else for from had
    has have how i if in is it its just know like me mentioned my of on or other our recall remember said say so
    talk talked tell than that the their them then there these they thing things this those to told us was we
    were what when where which who why will with would you your
""".split())


class _Source(NamedTuple):
    chat_id: str | None     # None for the memory from before chats
    title: str
    updated_at: str
    facts: list[str]
    messages: list[tuple[str, str]]     # (role, text)
    tainted: bool



def is_cross_chat_note(text: str) -> bool:
    return text.startswith("<cross_chat_access>")


def conversation(messages: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    """What the user and the agent said to each other, leaving out reasoning, tool calls and their results"""
    said = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or []
        # A user message carrying tool results is the harness continuing a reply, not the user speaking
        if role not in ("user", "assistant") or any("toolResult" in block for block in content):
            continue
        text = "\n".join(
            block["text"] for block in content
            # Notes sent ahead of a message (the user's time, a slash command's) are for the model, not part of the
            # conversation
            if isinstance(block.get("text"), str)
            and not is_cross_chat_note(block["text"]) and not is_code_note(block["text"])
            and not is_time_note(block["text"])
        ).strip()
        if text:
            said.append((role, text))
    return said


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"\W+", text.lower()) if len(token) > 1 and token not in _STOPWORDS}


def _snippet(text: str, query: set[str]) -> str:
    """The part of `text` around its first match, on one line"""
    text = " ".join(text.split())
    if len(text) <= SNIPPET_CHARS:
        return text
    lowered = text.lower()
    first = min((index for token in query if (index := lowered.find(token)) >= 0), default = 0)
    start = max(0, min(first - SNIPPET_CHARS // 3, len(text) - SNIPPET_CHARS))
    piece = text[start:start + SNIPPET_CHARS]
    return ("…" if start else "") + piece + ("…" if start + SNIPPET_CHARS < len(text) else "")


def _day(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %-d, %Y")
    except ValueError:
        return iso


def _label(source: _Source) -> str:
    return f'"{source.title}"' + (f" (chat {source.chat_id}, {_day(source.updated_at)})" if source.chat_id else "")



def chat_tools(store: ChatStore, chat_id: str) -> list[Any]:
    """
    The cross-chat tools for one chat: they see every chat except this one

    Args:
        store: {ChatStore} Where the chats live
        chat_id: {str} The chat the agent is in
    """
    # read_chat's own argument is named chat_id too, for the model's sake
    this_chat = chat_id

    def source(info: ChatInfo) -> _Source:
        messages, state = store.saved(info["id"])
        return _Source(
            chat_id = info["id"],
            title = info["title"],
            updated_at = info["updated_at"],
            facts = store.memories(info["id"]),
            messages = conversation(messages),
            tainted = bool(state.get(TAINT_STATE_KEY)),
        )


    def sources() -> list[_Source]:
        others = [info for info in store.recent() if info["id"] != this_chat]
        # Each chat takes a few reads, and those are round trips when the chats are on a server
        with ThreadPoolExecutor(max_workers = SOURCE_WORKERS) as pool:
            found = list(pool.map(source, others))
        if legacy := read_legacy_memories():
            found.append(_Source(None, _LEGACY_TITLE, "", legacy, [], False))
        return found


    def pass_on_taint(agent: Any, used: Iterable[_Source]) -> None:
        """Gate this chat if any text came from a chat that read untrusted web content; see TrustGate"""
        tainted = {f"chat {source.chat_id}" for source in used if source.tainted}
        if tainted:
            agent.state.set(TAINT_STATE_KEY, sorted(set(agent.state.get(TAINT_STATE_KEY) or []) | tainted))


    def overview(found: list[_Source]) -> tuple[str, list[_Source]]:
        shown = found[:OVERVIEW_CHATS]
        lines = [f"The user has {len(found)} other chat(s) with you, most recent first."]
        for source in shown:
            lines += ["", f"## {_label(source)}"]
            if source.facts:
                lines += ["Remembered:", *(f"- {' '.join(fact.split())}" for fact in source.facts[-OVERVIEW_FACTS:])]
            if source.messages:
                lines.append(f"Began with: {_snippet(source.messages[0][1], set())}")
        if len(found) > len(shown):
            lines += ["", f"({len(found) - len(shown)} older chats not shown; search for them by topic)"]
        return "\n".join(lines), shown


    def search(found: list[_Source], query: set[str]) -> tuple[str, list[_Source]]:
        hits: list[tuple[float, str, _Source]] = []
        for source in found:
            for fact in source.facts:
                if score := len(query & _tokens(fact)):
                    # Facts are already distilled, so they outrank a message that matches as well
                    hits.append((score + 0.5, f"[remembered] {_snippet(fact, query)}", source))
            for role, text in source.messages:
                if score := len(query & _tokens(text)):
                    hits.append((score, f"[{role}] {_snippet(text, query)}", source))
        if not hits:
            return "Nothing in the other chats matches. Try other words, or an empty query for an overview.", []

        # Most matched words first, then the most recent chat
        hits.sort(key = lambda hit: (hit[0], hit[2].updated_at), reverse = True)
        top = hits[:MAX_HITS]
        lines = [f"{len(top)} of {len(hits)} matches:"]
        lines += [f"- {_label(source)} {text}" for _, text, source in top]
        return "\n".join(lines), [source for _, _, source in top]


    @tool(context = True)
    def search_chats(tool_context: ToolContext, query: str = "") -> str:
        """
        Search the user's other chats with you for things they said or that you remember about them. Works only
        on messages the user started with /memory; otherwise it refuses

        Args:
            query: What to look for, e.g. "favorite coffee shop". Leave it empty for an overview of every other chat
        """
        if not tool_context.invocation_state.get(CROSS_CHAT):
            return _REFUSAL
        found = sources()
        if not found:
            return "The user has no other chats yet."
        terms = _tokens(query)
        text, used = search(found, terms) if terms else overview(found)
        pass_on_taint(tool_context.agent, used)
        return text


    @tool(context = True)
    def read_chat(tool_context: ToolContext, chat_id: str) -> str:
        """
        Read what was said in one of the user's other chats, e.g. one search_chats found. Works only on messages
        the user started with /memory; otherwise it refuses

        Args:
            chat_id: The chat's id, as search_chats shows it
        """
        if not tool_context.invocation_state.get(CROSS_CHAT):
            return _REFUSAL
        if chat_id == this_chat:
            return "That's this chat; everything said in it is already in your context."
        source = next((source for source in sources() if source.chat_id == chat_id), None)
        if source is None:
            return f"There's no other chat with the id {chat_id!r}. search_chats lists them."

        pass_on_taint(tool_context.agent, [source])
        transcript = "\n\n".join(f"{role}: {text}" for role, text in source.messages)
        if len(transcript) > READ_CHARS:
            transcript = "(earlier messages cut)\n\n…" + transcript[-READ_CHARS:]
        facts = "\n".join(f"- {' '.join(fact.split())}" for fact in source.facts)
        return "\n\n".join(part for part in (
            f"# {_label(source)}",
            f"Remembered:\n{facts}" if facts else "",
            transcript or "(no messages)",
        ) if part)


    return [search_chats, read_chat]
