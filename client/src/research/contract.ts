// Events a /research run sends inside `command_event`s; keep in step with agent/src/radagent/tools/research/events.py

export type Platform = "reference" | "news" | "academic" | "community" | "industry";
export type Phase = "planning" | "researching" | "writing" | "done";

export type AgentPlan = {
  /** e.g. "a1" */
  id: string;
  /** The angle it covers, e.g. "Manufacturing hurdles" */
  name: string;
  platform: Platform;
  /** What it's looking for */
  brief: string;
};

export type SearchHit = { url: string; title: string; published: string | null };

export type Source = {
  /** "S1", "S2", ... as the report cites them */
  id: string;
  url: string;
  title: string;
  published: string | null;
  /** The agent whose notes cited it first */
  agent: string;
};

export type ResearchEvent =
  | { kind: "phase"; phase: Phase }
  /** `date` is the day the research ran, e.g. "2026-10-02"; runs saved before it existed don't have one */
  | { kind: "plan"; title: string; agents: AgentPlan[]; date?: string }
  | { kind: "thought"; agent: string; text: string }
  | { kind: "search"; agent: string; query: string }
  | { kind: "results"; agent: string; query: string; hits: SearchHit[] }
  | { kind: "open"; agent: string; url: string }
  /** `url` is as opened; `screenshot` is a JPEG data URL of the top of the page, else `excerpt` has its text */
  | {
      kind: "page";
      agent: string;
      url: string;
      final_url: string;
      title: string;
      screenshot: string | null;
      pdf: boolean;
      excerpt: string | null;
    }
  | { kind: "page_failed"; agent: string; url: string; error: string }
  | { kind: "note"; agent: string; text: string; sources: string[] }
  | { kind: "agent_done"; agent: string; summary: string; error: string | null }
  | { kind: "sources"; sources: Source[] }
  /** Markdown that cites sources inline as [S3] */
  | { kind: "report_delta"; delta: string };

/** Events arrive untyped over the bridge; anything without a known kind is ignored rather than guessed at */
export function isResearchEvent(event: unknown): event is ResearchEvent {
  return typeof event === "object" && event !== null && typeof (event as { kind?: unknown }).kind === "string";
}
