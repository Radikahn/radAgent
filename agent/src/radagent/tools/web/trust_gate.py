import os
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry


# Tools that act on the machine, or read from it, so they must not run once untrusted web content is in the
# conversation: injected instructions could otherwise read a key and send it off with the next web request
GATED_TOOLS: frozenset[str] = frozenset({"shell", "read", "write", "edit"})
# File tools never touch these, tainted or not: process environments (keys, the runtime's AWS credentials), system
# configuration and credential files
_FILE_TOOLS: frozenset[str] = frozenset({"read", "write", "edit"})
_PROTECTED_ROOTS: tuple[str, ...] = ("/proc", "/sys", "/etc", "/root", "/var/run/secrets", "/run/secrets")
_PROTECTED_NAMES: frozenset[str] = frozenset({".env", ".aws", ".ssh", ".netrc", ".git-credentials", ".docker"})

# read_page opens its output with the URL the text really came from; web_search lists "N. Title — URL"
_PAGE_SOURCE = re.compile(r"\ASource: (\S+)")
_SEARCH_RESULT_URL = re.compile(r"(?m)^\d+\. .* — (https?://\S+)$")
# Tools whose results come from one fixed, publicly editable source
_FIXED_SOURCE_TOOLS: dict[str, str] = {"find_places": "https://www.openstreetmap.org"}
# Agent state key holding the taint; the session saves agent state, so a resumed chat stays gated
TAINT_STATE_KEY: str = "untrusted_sources"



class TrustGate(HookProvider):
    """
    Blocks shell, read, write and edit once the conversation holds web content from outside the trusted domains,
    and keeps the file tools away from credentials and system files always

    Web pages and search snippets can carry prompt injection, so after the agent reads anything untrusted it
    keeps its web tools but loses the ones that act on the machine or could read a secret off it. The taint lasts
    for the life of the conversation: it's kept in the agent's state, so a chat that is reopened with its old
    context is still gated, while a REPL /reset starts clean. Subagents and programmatic tool calls run under the same
    hooks, so they share the taint and can't be used to get around it
    """

    def __init__(self, trusted_domains: Iterable[str]) -> None:
        """
        Args:
            trusted_domains: {Iterable[str]} Domains whose content may steer the agent; subdomains are included
        """
        self.trusted_domains: tuple[str, ...] = tuple(domain.lower().strip(".") for domain in trusted_domains)
        self.untrusted_sources: set[str] = set()


    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._record_sources)
        registry.add_callback(BeforeToolCallEvent, self._gate)


    def is_trusted(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return bool(host) and any(host == domain or host.endswith("." + domain) for domain in self.trusted_domains)


    def record_urls(self, urls: Iterable[str]) -> None:
        """Note web content from `urls` that reached the conversation"""
        for url in urls:
            if not self.is_trusted(url):
                self.untrusted_sources.add(urlparse(url).hostname or url)


    def record_content(self, agent: Any, urls: Iterable[str]) -> None:
        """Note web content that reached `agent`'s conversation outside a tool call, e.g. a /research report"""
        self.record_urls(urls)
        # No tool call follows to save it, and the chat may be closed and reopened before one does
        self._sync(agent)


    def _sync(self, agent: Any) -> None:
        """Merge the taint saved in the agent's state with this gate's, and save the union back"""
        saved = agent.state.get(TAINT_STATE_KEY) or []
        self.untrusted_sources.update(saved)
        if len(self.untrusted_sources) != len(saved):
            agent.state.set(TAINT_STATE_KEY, sorted(self.untrusted_sources))


    def _record_sources(self, event: AfterToolCallEvent) -> None:
        self._record(event)
        self._sync(event.agent)


    def _record(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name not in ("web_search", "read_page", *_FIXED_SOURCE_TOOLS) or event.result.get("status") != "success":
            return

        text = "\n".join(block["text"] for block in event.result.get("content", []) if "text" in block).strip()
        if name in _FIXED_SOURCE_TOOLS:
            urls = [_FIXED_SOURCE_TOOLS[name]]
        elif name == "read_page":
            # Failures and empty pages carry no Source line and no page content
            match = _PAGE_SOURCE.match(text)
            urls = [match.group(1)] if match else []
        else:
            urls = _SEARCH_RESULT_URL.findall(text)
            if not urls and text != "No results." and not text.startswith("web_search failed"):
                # Results that can't be attributed to a domain can't be trusted
                self.untrusted_sources.add("unattributed web_search results")

        self.record_urls(urls)


    def _gate(self, event: BeforeToolCallEvent) -> None:
        self._sync(event.agent)
        name = event.tool_use["name"]
        if name in _FILE_TOOLS and (problem := _protected(event.tool_use.get("input"))):
            event.cancel_tool = f"{name} can't be used on {problem}: it holds credentials or system configuration."
            return
        if name not in GATED_TOOLS or not self.untrusted_sources:
            return

        sources = ", ".join(sorted(self.untrusted_sources))
        event.cancel_tool = (
            f"{event.tool_use['name']} is disabled for the rest of this session because the conversation contains "
            f"web content from untrusted sources ({sources}). Tell the user what you wanted to do so they can do it "
            f"themselves, or ask them to start a fresh session."
        )



def _protected(tool_input: object) -> str | None:
    """The protected path a file tool's input names, or None"""
    path = tool_input.get("path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path:
        return None
    resolved = os.path.realpath(os.path.expanduser(path))
    if any(resolved == root or resolved.startswith(root + "/") for root in _PROTECTED_ROOTS):
        return resolved
    parts = resolved.split("/")
    if any(part in _PROTECTED_NAMES or part.startswith(".env.") for part in parts):
        return resolved
    return None
