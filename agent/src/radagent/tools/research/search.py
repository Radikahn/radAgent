import asyncio
import contextlib
import html
import os
import re
import sys
import time
import weakref
from datetime import timedelta
from typing import TypedDict
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from strands.tools.mcp import MCPClient


# Research searches Exa first: the same hosted search the harness's web_search uses, called directly so research
# gets publish dates and can pass an objective, which steers Exa toward a kind of page (a Reddit thread, a paper)
EXA_MCP_URL: str = "https://mcp.exa.ai/mcp"
EXA_TOOL: str = "web_search_exa"
EXA_TIMEOUT: timedelta = timedelta(seconds = 30)
# Exa's keyless tier runs out quickly, so once it fails searches go to DuckDuckGo for a while before trying again
EXA_RETRY_AFTER_S: float = 600
DUCKDUCKGO_URL: str = "https://html.duckduckgo.com/html/"
DUCKDUCKGO_TIMEOUT_S: int = 15
USER_AGENT: str = "Mozilla/5.0 (compatible; radagent/0.1)"
SNIPPET_CHARS: int = 400
# Several agents search at once; the searches queue here so neither service sees a burst
MAX_CONCURRENT: int = 3

# One limit per event loop: the REPL runs each command on a fresh loop, and a semaphore can't cross loops
_slots: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
_exa_failed_at: float | None = None

_BLOCK_HEAD = re.compile(r"\s*Title: (.*)\r?\nURL: (\S+)")
_PUBLISHED = re.compile(r"(?m)^Published: (\d{4}-\d{2}-\d{2})")


class Hit(TypedDict):
    url: str
    title: str
    published: str | None   # ISO date
    snippet: str



# ---- Exa ----

def _parse_exa(text: str) -> list[Hit]:
    """Split Exa's `---` separated `Title:` / `URL:` / `Published:` / `Highlights:` blocks into hits"""
    hits: list[Hit] = []
    for block in re.split(r"(?m)^---\s*$", text):
        head = _BLOCK_HEAD.match(block)
        if not head:
            continue
        published = _PUBLISHED.search(block)
        highlights = block.split("Highlights:", 1)[1] if "Highlights:" in block else ""
        title = " ".join(head.group(1).split())
        hits.append({
            "url": head.group(2),
            # Exa writes N/A for pages it has no title for
            "title": "" if title == "N/A" else title,
            "published": published.group(1) if published else None,
            "snippet": " ".join(highlights.split())[:SNIPPET_CHARS],
        })
    return hits


def _search_exa(query: str, objective: str, count: int) -> list[Hit]:
    """One search over Exa's MCP server; the session lives only for this call"""
    key = os.environ.get("EXA_API_KEY")
    # Exa has taken the key under both names; sending both keeps working whichever it reads
    headers = {"x-api-key": key, "Authorization": f"Bearer {key}"} if key else None
    client = MCPClient(url = EXA_MCP_URL, headers = headers)
    try:
        client.start()
    except Exception as e:
        raise RuntimeError(f"could not reach Exa ({e})") from e
    try:
        result = client.call_tool_sync(
            tool_use_id = "research_search",
            name = EXA_TOOL,
            arguments = {"query": query, "objective": objective, "numResults": count},
            read_timeout_seconds = EXA_TIMEOUT,
        )
    finally:
        # A teardown error must not discard results already in hand
        with contextlib.suppress(Exception):
            client.stop(None, None, None)

    text = "\n".join(part for block in result["content"] if isinstance(part := block.get("text"), str))
    if result["status"] == "error":
        raise RuntimeError(text or "Exa reported an error")
    return _parse_exa(text)



# ---- DuckDuckGo ----

def _plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _result_url(href: str) -> str | None:
    """The page a DuckDuckGo result points to; its links sometimes go through a redirect, and ads go nowhere useful"""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        return target if target and target.startswith(("http://", "https://")) else None
    return href if parsed.scheme in ("http", "https") else None


def _search_duckduckgo(query: str, count: int) -> list[Hit]:
    """One search on DuckDuckGo's plain HTML page, which needs no key"""
    request = Request(DUCKDUCKGO_URL, data = urlencode({"q": query}).encode(), headers = {"User-Agent": USER_AGENT})
    with urlopen(request, timeout = DUCKDUCKGO_TIMEOUT_S) as response:
        page = response.read().decode("utf-8", errors = "replace")
    if "anomaly-modal" in page:
        raise RuntimeError("DuckDuckGo is asking for a human check, so it can't be searched for now")

    hits: list[Hit] = []
    for chunk in page.split('class="result__a"')[1:]:
        link = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        url = _result_url(link.group(1)) if link else None
        if not link or not url:
            continue
        snippet = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', chunk, re.S)
        hits.append({
            "url": url,
            "title": _plain(link.group(2)),
            "published": None,
            "snippet": _plain(snippet.group(1))[:SNIPPET_CHARS] if snippet else "",
        })
        if len(hits) == count:
            break
    return hits



async def search(query: str, objective: str, count: int) -> list[Hit]:
    """
    Search the web through Exa, or DuckDuckGo while Exa is failing (its keyless tier is rate limited)

    Args:
        query: {str} A description of the ideal page, e.g. "Reddit thread where owners compare heat pumps"
        objective: {str} What this search is for, so Exa ranks the right kind of page first
        count: {int} How many hits to return

    Returns:
        hits: {list[Hit]} Best first

    Raises:
        RuntimeError: When neither service could search
    """
    global _exa_failed_at
    slots = _slots.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(MAX_CONCURRENT))
    async with slots:
        exa_problem = "skipped after failing recently"
        if _exa_failed_at is None or time.monotonic() - _exa_failed_at > EXA_RETRY_AFTER_S:
            try:
                hits = await asyncio.to_thread(_search_exa, query, objective, count)
                _exa_failed_at = None
                return hits
            except Exception as e:
                _exa_failed_at = time.monotonic()
                exa_problem = str(e).splitlines()[0] if str(e) else type(e).__name__
                print(f"[radagent] Exa search failed, using DuckDuckGo: {exa_problem}", file = sys.stderr)

        try:
            return await asyncio.to_thread(_search_duckduckgo, query, count)
        except Exception as e:
            hint = "" if os.environ.get("EXA_API_KEY") else "; setting EXA_API_KEY lifts Exa's rate limit"
            raise RuntimeError(f"Exa ({exa_problem}) and DuckDuckGo ({e}) both failed{hint}") from e
