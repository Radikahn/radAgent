import asyncio
import base64
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag, urlparse

from strands import Agent, tool
from strands.models import Model, ModelRouter

from radagent.tools.research.events import AgentPlan, Emit
from radagent.tools.research.prompts import PLATFORMS, RESEARCHER_PROMPT
from radagent.tools.research.search import search
from radagent.tools.web import capture_page


MAX_SEARCHES: int = 4
MAX_PAGES: int = 5
HITS_PER_SEARCH: int = 6
# Page text beyond this is cut; five pages of it still leave the agent plenty of room
PAGE_CHARS: int = 8_000
# A page with no screenshot (a PDF, say) shows the start of its text in the window instead
EXCERPT_CHARS: int = 1_200
# The agent's latest words go to its window at most this often, and only the tail of them
THOUGHT_INTERVAL_S: float = 0.4
THOUGHT_CHARS: int = 220



def canonical(url: str) -> str:
    """The form two links to the same page share: no fragment, no trailing slash"""
    return urldefrag(url.strip()).url.rstrip("/")


@dataclass
class Page:
    url: str
    title: str
    published: str | None


@dataclass
class Note:
    text: str
    sources: list[str]      # URLs, each a key of `Findings.pages` once canonical


@dataclass
class Findings:
    """What one agent brings back: its notes, every page it came across, and its own summary"""
    plan: AgentPlan
    notes: list[Note] = field(default_factory = list)
    pages: dict[str, Page] = field(default_factory = dict)   # By canonical URL
    summary: str = ""
    error: str | None = None



class Researcher:
    """
    One research agent covering one angle of the topic, on its own Strands agent

    Its tools are bound to it, so everything it searches, opens and notes is both recorded in its findings and sent
    to its window on the client as it happens. The budget lives in the tools rather than the prompt: once spent, the
    tools say so and the agent wraps up. Notes are kept as they're made, so an agent stopped early keeps its work
    """

    def __init__(self, plan: AgentPlan, topic: str, model: Model | ModelRouter, emit: Emit, today: str) -> None:
        self.plan = plan
        self.findings = Findings(plan = plan)
        self._emit = emit
        self._searches = 0
        self._pages = 0
        self._thought = ""
        self._thought_kind = ""
        self._thought_sent = ""
        self._thought_sent_at = 0.0

        guide = PLATFORMS[plan["platform"]]
        # Exa ranks by this alongside the query; it keeps every search on the agent's platform without the model
        # having to say so each time
        self._objective = f"{plan['brief']} Prefer {guide.covers}."
        self.agent = Agent(
            model = model,
            tools = self._tools(),
            system_prompt = RESEARCHER_PROMPT.format(
                topic = topic,
                name = plan["name"],
                brief = plan["brief"],
                platform_label = guide.label,
                platform_covers = guide.covers,
                platform_phrasing = guide.phrasing,
                max_searches = MAX_SEARCHES,
                max_pages = MAX_PAGES,
                today = today,
            ),
            callback_handler = None,
        )


    # ---- Tools ----

    def _tools(self) -> list[Any]:
        agent_id = self.plan["id"]
        pages = self.findings.pages

        @tool(name = "search")
        async def search_tool(query: str) -> str:
            """Search the web. Returns numbered results with title, date, URL and an excerpt.

            Args:
                query: A description of the ideal page, e.g. "Reddit thread where owners compare heat pump brands", not bare keywords.
            """
            if self._searches >= MAX_SEARCHES:
                return "Search budget used up. Open the best results you already have, note what you learn, then finish."
            self._searches += 1
            self._emit({"kind": "search", "agent": agent_id, "query": query})

            try:
                hits = await search(query, self._objective, HITS_PER_SEARCH)
            except Exception as e:
                self._emit({"kind": "results", "agent": agent_id, "query": query, "hits": []})
                return f"search failed: {e}"

            for hit in hits:
                pages.setdefault(canonical(hit["url"]), Page(hit["url"], hit["title"], hit["published"]))
            self._emit({
                "kind": "results",
                "agent": agent_id,
                "query": query,
                "hits": [{"url": hit["url"], "title": hit["title"], "published": hit["published"]} for hit in hits],
            })
            if not hits:
                return "No results. Describe the page you want differently."

            lines = [f"Results ({MAX_SEARCHES - self._searches} searches left):"]
            for number, hit in enumerate(hits, start = 1):
                published = f" ({hit['published']})" if hit["published"] else ""
                lines.append(f"{number}. {hit['title'] or '(untitled)'}{published} — {hit['url']}")
                if hit["snippet"]:
                    lines.append(f"   {hit['snippet']}")
            return "\n".join(lines)


        @tool
        async def open_page(url: str) -> str:
            """Open a web page and read its text. The user watches the page load in your window.

            Args:
                url: The http(s) URL to open, usually one from your search results.
            """
            if self._pages >= MAX_PAGES:
                return "Page budget used up. Note what you learned, then finish."
            self._pages += 1
            self._emit({"kind": "open", "agent": agent_id, "url": url})

            try:
                capture = await capture_page(url)
            except Exception as e:
                self._emit({"kind": "page_failed", "agent": agent_id, "url": url, "error": str(e)[:300]})
                return f"open_page failed: {e}. Try another result."

            known = pages.get(canonical(url))
            # A PDF's own title is often a file name or nothing, so the search result's title wins for those
            titles = [known.title if known else "", capture.title] if capture.pdf else [capture.title, known.title if known else ""]
            title = next((" ".join(title.split()) for title in titles if title.strip()), urlparse(url).hostname or url)
            page = Page(url, title, known.published if known else None)
            # Notes may cite the link as searched or where it redirected to; both lead to this page
            pages[canonical(url)] = page
            pages.setdefault(canonical(capture.url), page)

            text = re.sub(r"\n\s*\n\s*", "\n\n", capture.text).strip()
            screenshot = capture.screenshot and "data:image/jpeg;base64," + base64.b64encode(capture.screenshot).decode()
            self._emit({
                "kind": "page",
                "agent": agent_id,
                "url": url,
                "final_url": capture.url,
                "title": title,
                "screenshot": screenshot or None,
                "pdf": capture.pdf,
                "excerpt": None if screenshot else text[:EXCERPT_CHARS],
            })

            if len(text) > PAGE_CHARS:
                text = text[:PAGE_CHARS] + "\n[truncated]"
            return f"Source: {url}\nTitle: {title}\n({MAX_PAGES - self._pages} pages left)\n\n{text}"


        @tool
        def note(finding: str, sources: list[str]) -> str:
            """Record one finding for the report. Call this as soon as you learn something useful; the report is written only from notes.

            Args:
                finding: One specific, self-contained finding: the fact, figure or claim, with who says so and when.
                sources: URLs of the pages or search results that support it.
            """
            finding = " ".join(finding.split())
            cited = [pages[key].url for key in dict.fromkeys(canonical(url) for url in sources) if key in pages]
            if not finding:
                return "Not noted: the finding was empty."
            if not cited:
                return "Not noted: cite at least one URL you found through search or open_page."

            self.findings.notes.append(Note(finding, cited))
            self._emit({"kind": "note", "agent": agent_id, "text": finding, "sources": cited})
            return f"Noted ({len(self.findings.notes)} so far)."

        return [search_tool, open_page, note]


    # ---- What the agent says, shown in its window ----

    def _send_thought(self) -> None:
        # The window shows one plain line, so Markdown markers would only be noise
        text = " ".join(re.sub(r"[#*_`>|]+", " ", self._thought).split())
        if len(text) > THOUGHT_CHARS:
            # Keep the tail, starting at a word
            text = "…" + text[-THOUGHT_CHARS:].split(" ", 1)[-1]
        if text and text != self._thought_sent:
            self._emit({"kind": "thought", "agent": self.plan["id"], "text": text})
            self._thought_sent = text
        self._thought_sent_at = time.monotonic()


    def _watch(self, event: dict[str, Any]) -> None:
        for kind in ("reasoningText", "data"):
            delta = event.get(kind)
            if isinstance(delta, str) and delta:
                # Thinking and the reply are separate trains of thought; don't run one into the other
                if kind != self._thought_kind:
                    self._thought, self._thought_kind = "", kind
                self._thought += delta
                if time.monotonic() - self._thought_sent_at >= THOUGHT_INTERVAL_S:
                    self._send_thought()

        chunk = event.get("event")
        if isinstance(chunk, dict) and chunk.get("contentBlockStart", {}).get("start", {}).get("toolUse"):
            self._send_thought()
            self._thought, self._thought_kind = "", ""


    # ---- Running ----

    async def run(self, timeout_s: float) -> Findings:
        """
        Research the angle until the agent finishes, its budget runs out or `timeout_s` passes

        Args:
            timeout_s: {float} Wall-clock limit; the agent's notes so far are kept when it's reached

        Returns:
            findings: {Findings}
        """
        findings = self.findings
        try:
            async with asyncio.timeout(timeout_s):
                async for event in self.agent.stream_async(f"Research your angle now: {self.plan['brief']}"):
                    self._watch(event)
                    if "result" in event:
                        findings.summary = str(event["result"]).strip()
        except TimeoutError:
            self.agent.cancel()
            findings.summary = findings.summary or "Stopped at the time limit."
        except asyncio.CancelledError:
            # The whole run was stopped; tell the model loop too, since its request runs on a worker thread
            self.agent.cancel()
            raise
        except Exception as e:
            findings.error = f"{type(e).__name__}: {e}"

        self._send_thought()
        self._emit({"kind": "agent_done", "agent": self.plan["id"], "summary": findings.summary, "error": findings.error})
        return findings
