import { isResearchEvent, type AgentPlan, type Phase, type SearchHit, type Source } from "./contract";

/** What an agent's window shows right now */
export type View =
  | { kind: "blank" }
  | { kind: "search"; query: string; hits: SearchHit[] | null }
  | {
      kind: "page";
      url: string;
      finalUrl?: string;
      title?: string;
      screenshot?: string | null;
      pdf?: boolean;
      /** The start of its text, shown when there's no screenshot */
      excerpt?: string | null;
      status: "loading" | "loaded" | "failed";
      error?: string;
    };

export type PageView = Extract<View, { kind: "page" }>;

export type AgentStatus = "starting" | "thinking" | "searching" | "reading" | "done" | "failed";

export type AgentState = {
  plan: AgentPlan;
  status: AgentStatus;
  view: View;
  /** The latest line of what the agent is saying or thinking */
  thought: string;
  queries: string[];
  /** Every page it opened, in order */
  pages: PageView[];
  notes: { text: string; sources: string[]; at: number }[];
  summary?: string;
  error?: string;
};

export type ResearchState = {
  phase: Phase;
  title?: string;
  /** The day the research ran, e.g. "2026-10-02" */
  date?: string;
  agents: AgentState[];
  /** Numbered once the agents are done; the report cites them by id */
  sources: Source[];
  /** The report's Markdown so far */
  report: string;
  startedAt: number;
  endedAt?: number;
};

const EMPTY = (at: number): ResearchState => ({ phase: "planning", agents: [], sources: [], report: "", startedAt: at });

function updateAgent(state: ResearchState, id: string, update: (agent: AgentState) => AgentState): ResearchState {
  return { ...state, agents: state.agents.map((agent) => (agent.plan.id === id ? update(agent) : agent)) };
}

/** Applies `update` to the latest visit to `url`, and to the view when it's showing that page */
function updatePage(agent: AgentState, url: string, update: Partial<PageView>): AgentState {
  let index = -1;
  agent.pages.forEach((page, i) => {
    if (page.url === url) index = i;
  });
  if (index < 0) return agent;

  const page = { ...agent.pages[index], ...update };
  const pages = agent.pages.map((visit, i) => (i === index ? page : visit));
  // A page that finished loading takes over the window even if another opened since: it's what the agent now reads
  const showing = agent.view.kind === "page" && agent.view.url === url;
  return { ...agent, pages, view: showing || update.status === "loaded" ? page : agent.view };
}

const working = (agent: AgentState) => agent.status !== "done" && agent.status !== "failed";

/** Folds one event from the agent process into the run's state; events of unknown kinds change nothing */
export function reduceResearch(previous: ResearchState | undefined, event: unknown, at: number): ResearchState {
  const state = previous ?? EMPTY(at);
  if (!isResearchEvent(event)) return state;

  switch (event.kind) {
    case "phase":
      return { ...state, phase: event.phase, endedAt: event.phase === "done" ? at : state.endedAt };
    case "plan":
      return {
        ...state,
        title: event.title,
        date: event.date,
        agents: event.agents.map((plan) => ({
          plan,
          status: "starting",
          view: { kind: "blank" },
          thought: "",
          queries: [],
          pages: [],
          notes: [],
        })),
      };
    case "thought":
      return updateAgent(state, event.agent, (agent) => ({
        ...agent,
        thought: event.text,
        status: working(agent) && agent.status !== "reading" ? "thinking" : agent.status,
      }));
    case "search":
      return updateAgent(state, event.agent, (agent) => ({
        ...agent,
        status: "searching",
        view: { kind: "search", query: event.query, hits: null },
        queries: [...agent.queries, event.query],
      }));
    case "results":
      return updateAgent(state, event.agent, (agent) => ({
        ...agent,
        status: working(agent) ? "thinking" : agent.status,
        view:
          agent.view.kind === "search" && agent.view.query === event.query
            ? { ...agent.view, hits: event.hits }
            : agent.view,
      }));
    case "open": {
      const page: PageView = { kind: "page", url: event.url, status: "loading" };
      return updateAgent(state, event.agent, (agent) => ({
        ...agent,
        status: "reading",
        view: page,
        pages: [...agent.pages, page],
      }));
    }
    case "page":
      return updateAgent(state, event.agent, (agent) =>
        updatePage(agent, event.url, {
          status: "loaded",
          finalUrl: event.final_url,
          title: event.title,
          screenshot: event.screenshot,
          pdf: event.pdf,
          excerpt: event.excerpt,
        }),
      );
    case "page_failed":
      return updateAgent(state, event.agent, (agent) => ({
        ...updatePage(agent, event.url, { status: "failed", error: event.error }),
        status: working(agent) ? "thinking" : agent.status,
      }));
    case "note":
      return updateAgent(state, event.agent, (agent) => ({
        ...agent,
        notes: [...agent.notes, { text: event.text, sources: event.sources, at }],
      }));
    case "agent_done":
      return updateAgent(state, event.agent, (agent) => ({
        ...agent,
        status: event.error ? "failed" : "done",
        summary: event.summary,
        error: event.error ?? undefined,
      }));
    case "sources":
      return { ...state, sources: event.sources };
    case "report_delta":
      return { ...state, report: state.report + event.delta };
  }
}
