import asyncio
from dotenv import load_dotenv
from pathlib import Path
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, cast
from os import getenv

from radagent.chats import ChatStore
from radagent.config import MODEL, TRUSTED_DOMAINS
from radagent.media import Attachment, MediaGuard, prompt_content

from radagent.prompts.lib.prompt import initalize_agent
from radagent.tools import TOOLS
from radagent.tools.chats import CROSS_CHAT, CROSS_CHAT_NOTE, chat_tools
from radagent.tools.web import TrustGate
from strands.agent import AgentResult
from strands_harness import create_harness
from strands_harness.memory import MEMORY_STORE_NAME, resolve_memory
from strands_harness.models import resolve_web_fetch_model
from strands.memory import ExtractionConfig, MemoryManager, MemoryStore, ModelExtractor
from strands.session import SnapshotSessionManager
from strands.storage import LocalFileStorage, S3Storage
from strands.vended_memory_stores.file_memory_store import FileMemoryStore
from strands.vended_plugins.context_offloader import ContextOffloader
from strands import Agent


# Agent runtime configuratin
load_dotenv()
SYSTEM_PROMPT: str = initalize_agent()

# A chat's offloader matches the harness's own: tool results over this many tokens leave the context, keeping a preview
OFFLOAD_MAX_RESULT_TOKENS: int = 1_500
OFFLOAD_PREVIEW_TOKENS: int = 750



def _user_turn_memory(model: str, storage: LocalFileStorage | S3Storage | None = None) -> MemoryManager:
    """
    The harness's own memory, but recalled only when the user speaks

    The harness recalls memory before every model call and appends it as a text block to the latest user
    message. On a tool-result turn that block sits alone beside the results, so the model reads it as the user
    sending an empty message and says so. There is no public option for the trigger yet, hence the private
    attribute; if a harness update renames it this fails loudly at startup instead of silently regressing.
    Trade-off: a manager passed in explicitly isn't shared with `subagent` delegates, so they run without memory

    Args:
        model: {str} The agent's model; facts are distilled by the small model the harness pairs with it
        storage: {LocalFileStorage | S3Storage | None} Where the facts go, one markdown file each; None for the
                 harness's `.agent/memory`
    """
    stores: list[MemoryStore] | None = None
    if storage is not None:
        # The store the harness builds for a memory folder, over storage that may be a bucket instead.
        # namespace("") keeps the files directly in `storage` rather than under the store's own memory/<name>/
        # The cast: FileMemoryStore sets the protocol's attributes in __init__, which type checkers don't count
        stores = [cast(MemoryStore, FileMemoryStore(
            name = MEMORY_STORE_NAME,
            storage = storage.namespace(""),
            writable = True,
            extraction = ExtractionConfig(extractor = ModelExtractor(model = resolve_web_fetch_model(model, None))),
        ))]
    memory = resolve_memory(stores = stores, model = model)
    if not isinstance(getattr(memory, "_injection_config", None), dict):
        raise RuntimeError("strands MemoryManager no longer has _injection_config; revisit _user_turn_memory")
    memory._injection_config = {**memory._injection_config, "trigger": "userTurn"}
    return memory



class RadAgent:
    def __init__(
        self,
        model: str | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        callback_handler: Callable[..., Any] | None = None,
        chat_id: str | None = None,
        chats: ChatStore | None = None
    ) -> None:
        """
        Initialize a RadAgent with all configuration and system prompts

        Args:
            model: {str} Default model is defined in `config.py`
            system_prompt: {str} Default is the prompt in `prompts/system_prompt.txt`
            callback_handler: {Callable | None} Receives streamed events; Strands prints to stdout when omitted
            chat_id: {str | None} The desktop chat this agent serves: it picks up that chat's saved context, keeps
                     its own memory, and can look through the other chats on /memory messages. Without one the
                     agent starts a fresh session and shares the memory in `.agent/memory`
            chats: {ChatStore | None} Where chats live; defaults to the bucket or `.agent/chats`, see radagent.storage
        """
        if not model: model = MODEL
        # Slash commands that run their own agents (e.g. /research) follow the conversation's model
        self.model: str = model

        # Only pass the handler when given, so Strands keeps its default printer otherwise
        agent_kwargs: dict[str, Any] = {}
        if callback_handler is not None:
            agent_kwargs["callback_handler"] = callback_handler

        # Each agent gets its own gate; a resumed chat gets its taint back from the agent state its session saved
        self.trust_gate = TrustGate(trusted_domains = TRUSTED_DOMAINS)

        tools = list(TOOLS)
        session: Any = True
        memory_storage: LocalFileStorage | S3Storage | None = None
        plugins: list[Any] = []
        if chat_id is not None:
            chats = chats or ChatStore()
            # The harness saves the conversation into the chat's folder and restores it when an agent reopens the
            # chat. This is the manager it builds from {"id", "dir"}, given storage that may be a bucket instead
            session = SnapshotSessionManager(chat_id, storage = chats.storage(chat_id), save_latest_on = "message")
            memory_storage = chats.storage(chat_id, "memory")
            # Handed a session manager, the harness would offload large tool results to a temporary folder; these
            # are its own thresholds, and nothing is evicted, so a reopened chat can still fetch what it offloaded
            plugins.append(ContextOffloader(
                storage = chats.storage(chat_id, "offloaded"),
                max_result_tokens = OFFLOAD_MAX_RESULT_TOKENS,
                preview_tokens = OFFLOAD_PREVIEW_TOKENS,
                evict_after_cycles = None,
            ))
            tools += chat_tools(chats, chat_id)

        # Bedrock has no native web search, so search runs through Exa (EXA_API_KEY lifts its rate limit)
        # read_page replaces the built-in web_fetch with a plain-fetch -> headless-browser fallback
        # The built-in `read` shows the model local images, PDFs and Office files; MediaGuard keeps those (and
        # read_page's) within Bedrock's size limits so one large file can't break the conversation
        self.AGENT: Agent = create_harness(
            model = model,
            instructions = system_prompt,
            tools = tools,
            builtin_tools = {"web_search": "exa", "web_fetch": False},
            hooks = [self.trust_gate, MediaGuard()],
            session = session,
            plugins = plugins,
            memory = _user_turn_memory(model, memory_storage),
            **agent_kwargs
        )


    def query(self, query: str, attachments: Sequence[Attachment] = (), **kwargs) -> AgentResult:
        """
        Pass provided query to strands agent

        System prompts and tooling are also passed within this request
        The intended use is when user asks the agent a question through normal converstaion and expects agent character
        response

        Args:
            query: {str}
            attachments: {Sequence[Attachment]} Images, PDFs, Office and text files sent along with the query
            **kwargs

        Returns:
            response: {AgentResult}

        Raises:
            MediaError: An attachment is in a format the model can't read or too large to send
        """

        ##TODO: Handle kwargs
        response: AgentResult = self.AGENT(prompt = prompt_content(query, list(attachments)))

        return response


    async def stream(
        self, query: str, cross_chat: bool = False, attachments: Sequence[Attachment] = ()
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Pass provided query to strands agent and stream the response as it is generated

        Args:
            query: {str}
            cross_chat: {bool} Let this message look through the user's other chats (the /memory command)
            attachments: {Sequence[Attachment]} Images, PDFs, Office and text files sent along with the query

        Returns:
            events: {AsyncIterator[dict]} Strands stream events; the last one holds the `result` {AgentResult}

        Raises:
            MediaError: An attachment is in a format the model can't read or too large to send
        """
        # Shrinking a large photo takes a moment, so it runs off the event loop
        prompt = await asyncio.to_thread(prompt_content, query, list(attachments)) if attachments else query
        kwargs: dict[str, Any] = {}
        if cross_chat:
            # The note tells the model it may look; the flag is what actually unlocks the tools, for this turn only.
            # It stays a block of its own, which is how the chat history knows to hide it
            blocks = prompt if isinstance(prompt, list) else [{"text": prompt}]
            prompt = [{"text": CROSS_CHAT_NOTE}, *blocks]
            kwargs["invocation_state"] = {CROSS_CHAT: True}
        async for event in self.AGENT.stream_async(prompt, **kwargs):
            yield event


    def cancel(self) -> None:
        """Stop the running response at the next safe point; safe to call from any thread"""
        self.AGENT.cancel()


    async def close(self) -> None:
        """Flush pending memory extraction so facts from this conversation aren't lost"""
        await self.AGENT.shutdown_async()
