"""
Events a /research run sends while it works, so the client can show every agent's window live

The run emits these in order: phase "planning", a plan naming the agents, phase "researching" with each agent's
thoughts, searches, pages and notes interleaved, phase "writing" with the numbered sources and the report as it
streams, then phase "done". Each event is small except `page`, which carries a JPEG screenshot as a data URL

Keep these types in step with `client/src/research/contract.ts`
"""
from collections.abc import Callable
from typing import Literal, TypedDict


Platform = Literal["reference", "news", "academic", "community", "industry"]
Phase = Literal["planning", "researching", "writing", "done"]


class AgentPlan(TypedDict):
    id: str                     # e.g. "a1"
    name: str                   # The angle it covers, e.g. "Manufacturing hurdles"
    platform: Platform
    brief: str                  # What it's looking for


class SearchHit(TypedDict):
    url: str
    title: str
    published: str | None       # ISO date, e.g. "2026-07-29"


class Source(TypedDict):
    id: str                     # "S1", "S2", ... as the report cites them
    url: str
    title: str
    published: str | None
    agent: str                  # The agent whose notes cited it first


class PhaseEvent(TypedDict):
    kind: Literal["phase"]
    phase: Phase


class PlanEvent(TypedDict):
    kind: Literal["plan"]
    title: str
    agents: list[AgentPlan]
    date: str                   # The day the research ran, ISO, e.g. "2026-10-02"; exports are dated by it


class ThoughtEvent(TypedDict):
    kind: Literal["thought"]
    agent: str
    text: str                   # The latest line of what the agent is saying or thinking


class SearchEvent(TypedDict):
    kind: Literal["search"]
    agent: str
    query: str


class ResultsEvent(TypedDict):
    kind: Literal["results"]
    agent: str
    query: str
    hits: list[SearchHit]


class OpenEvent(TypedDict):
    kind: Literal["open"]
    agent: str
    url: str


class PageEvent(TypedDict):
    kind: Literal["page"]
    agent: str
    url: str                    # As opened, matching the `open` event
    final_url: str              # Where it ended up after redirects
    title: str
    screenshot: str | None      # data:image/jpeg;base64,...
    pdf: bool
    excerpt: str | None         # The start of its text, to show in place of a missing screenshot


class PageFailedEvent(TypedDict):
    kind: Literal["page_failed"]
    agent: str
    url: str
    error: str


class NoteEvent(TypedDict):
    kind: Literal["note"]
    agent: str
    text: str
    sources: list[str]          # URLs


class AgentDoneEvent(TypedDict):
    kind: Literal["agent_done"]
    agent: str
    summary: str
    error: str | None


class SourcesEvent(TypedDict):
    kind: Literal["sources"]
    sources: list[Source]


class ReportDeltaEvent(TypedDict):
    kind: Literal["report_delta"]
    delta: str                  # Markdown; `[S3]` cites a source by id


ResearchEvent = (
    PhaseEvent | PlanEvent | ThoughtEvent | SearchEvent | ResultsEvent | OpenEvent | PageEvent | PageFailedEvent
    | NoteEvent | AgentDoneEvent | SourcesEvent | ReportDeltaEvent
)

Emit = Callable[[ResearchEvent], None]
