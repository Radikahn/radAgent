import asyncio
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from strands import Agent
from strands_harness import Effort
from strands_harness.models import resolve_model

from radagent.tools.research.events import AgentPlan, Emit, Platform, Source
from radagent.tools.research.prompts import PLANNER_PROMPT, PLATFORMS, WRITER_PROMPT, platform_list
from radagent.tools.research.researcher import Findings, Researcher, canonical


MIN_AGENTS: int = 3
MAX_AGENTS: int = 5
# Each agent's wall-clock limit; its notes so far still reach the report
AGENT_TIMEOUT_S: float = 150
# Thinking effort per role: planning is simple, research is many quick steps, the report is worth some thought
PLANNER_EFFORT: Effort = "off"      # Off also because structured output may force a tool, which thinking forbids
RESEARCHER_EFFORT: Effort = "off"
WRITER_EFFORT: Effort = "medium"



class ResearchError(Exception):
    """The run couldn't produce a report; the message says why"""


@dataclass(frozen = True)
class ResearchReport:
    title: str
    text: str                   # The writer's Markdown, citing sources inline as [S1], [S2], ...
    sources: list[Source]


    def markdown(self) -> str:
        """The report with its numbered sources listed after it, for the conversation history and the terminal"""
        listing = "\n".join(f"- [{source['id']}] {source['title']} — {source['url']}" for source in self.sources)
        return f"{self.text.strip()}\n\n**Sources**\n\n{listing}"



class _Angle(BaseModel):
    name: str = Field(description = "Two to four words naming the angle")
    platform: Platform
    brief: str = Field(description = "One or two sentences on exactly what this agent should find out")


class _Plan(BaseModel):
    title: str = Field(description = "A short title for the research, at most eight words")
    angles: list[_Angle] = Field(min_length = 1)



async def _plan(topic: str, model: str, today: str) -> tuple[str, list[AgentPlan]]:
    planner = Agent(
        model = resolve_model(model, model, effort = PLANNER_EFFORT),
        system_prompt = PLANNER_PROMPT.format(
            min_agents = MIN_AGENTS, max_agents = MAX_AGENTS, platforms = platform_list(), today = today
        ),
        callback_handler = None,
    )
    result = await planner.invoke_async(f"Topic: {topic}", structured_output_model = _Plan)
    plan = result.structured_output
    if not isinstance(plan, _Plan):
        raise ResearchError("The planner didn't return a plan")

    agents: list[AgentPlan] = [
        {"id": f"a{number}", "name": angle.name.strip(), "platform": angle.platform, "brief": angle.brief.strip()}
        for number, angle in enumerate(plan.angles[:MAX_AGENTS], start = 1)
    ]
    return plan.title.strip() or topic, agents


def _number_sources(crew: list[Findings]) -> tuple[list[Source], dict[str, str]]:
    """
    Give every cited page a report-wide id, in the order the notes cite them

    Returns:
        (sources, ids): {tuple[list[Source], dict[str, str]]} ids maps a canonical URL to its source id
    """
    sources: list[Source] = []
    ids: dict[str, str] = {}
    for findings in crew:
        for note in findings.notes:
            for url in note.sources:
                key = canonical(url)
                if key in ids:
                    continue
                page = findings.pages[key]
                ids[key] = f"S{len(sources) + 1}"
                sources.append({
                    "id": ids[key],
                    "url": page.url,
                    # Cited from an untitled search result and never opened, the site has to name it
                    "title": page.title or urlparse(page.url).hostname or page.url,
                    "published": page.published,
                    "agent": findings.plan["id"],
                })
    return sources, ids


def _writer_brief(topic: str, title: str, crew: list[Findings], sources: list[Source], ids: dict[str, str]) -> str:
    """Everything the writer works from: the numbered sources and each agent's notes citing them by id"""
    lines = [f"Topic: {topic}", f"Working title: {title}", "", "Sources:"]
    for source in sources:
        published = f" ({source['published']})" if source["published"] else ""
        lines.append(f"[{source['id']}] {source['title']}{published} — {source['url']}")

    for findings in crew:
        if not findings.notes:
            continue
        plan = findings.plan
        lines += ["", f"## {plan['name']} ({PLATFORMS[plan['platform']].label})", f"Brief: {plan['brief']}"]
        for note in findings.notes:
            cites = "".join(f"[{ids[canonical(url)]}]" for url in note.sources)
            lines.append(f"- {note.text} {cites}")
        if findings.summary:
            lines.append(f"Agent's summary: {findings.summary}")
    return "\n".join(lines)



async def run_research(topic: str, *, model: str, agent_model: str, emit: Emit) -> ResearchReport:
    """
    Research `topic` with a crew of agents and write a cited report, reporting progress through `emit`

    A planner splits the topic into angles, one agent per angle researches in parallel on its own platform (news,
    papers, forums and so on), and a writer turns their notes into a report that cites sources as [S1], [S2], ...

    Args:
        topic: {str} What to research
        model: {str} Model ID for the planner and the report writer
        agent_model: {str} Model ID for the research agents
        emit: {Emit} Receives every progress event; see events.py

    Returns:
        report: {ResearchReport}

    Raises:
        ResearchError: When there's no plan or the agents found nothing citable
    """
    today = date.today().isoformat()

    emit({"kind": "phase", "phase": "planning"})
    title, agents = await _plan(topic, model, today)
    emit({"kind": "plan", "title": title, "agents": agents, "date": today})

    emit({"kind": "phase", "phase": "researching"})
    # Each agent gets its own model client; they run side by side
    researchers = [
        Researcher(
            agent, topic, resolve_model(agent_model, agent_model, effort = RESEARCHER_EFFORT, caching = True), emit, today
        )
        for agent in agents
    ]
    crew = await asyncio.gather(*(researcher.run(AGENT_TIMEOUT_S) for researcher in researchers))

    sources, ids = _number_sources(crew)
    if not sources:
        failures = [f"{findings.plan['name']}: {findings.error}" for findings in crew if findings.error]
        detail = f" ({'; '.join(failures)})" if failures else ""
        raise ResearchError(f"The research agents didn't find anything they could cite{detail}")

    emit({"kind": "sources", "sources": sources})
    emit({"kind": "phase", "phase": "writing"})
    writer = Agent(
        model = resolve_model(model, model, effort = WRITER_EFFORT, caching = True),
        system_prompt = WRITER_PROMPT.format(today = today),
        callback_handler = None,
    )
    text = ""
    async for event in writer.stream_async(_writer_brief(topic, title, crew, sources, ids)):
        if delta := event.get("data"):
            text += delta
            emit({"kind": "report_delta", "delta": delta})

    emit({"kind": "phase", "phase": "done"})
    return ResearchReport(title = title, text = text, sources = sources)
