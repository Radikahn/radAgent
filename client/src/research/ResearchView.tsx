import { memo, useEffect, useMemo, useState } from "react";
import type { Phase } from "./contract";
import type { ResearchState } from "./state";
import { AgentWindow, agentHue } from "./AgentWindow";
import { parseReport } from "./parse";
import { Report } from "./Report";
import { ExportBar } from "./ExportBar";
import { PlatformIcon } from "./parts";
import "./research.css";

const STEPS: { phase: Phase; label: string }[] = [
  { phase: "planning", label: "Plan" },
  { phase: "researching", label: "Research" },
  { phase: "writing", label: "Write" },
];

const ORDER: Phase[] = ["planning", "researching", "writing", "done"];

/** Re-renders every second while `active`, for the elapsed clock */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function clock(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function Steps({ phase, live }: { phase: Phase; live: boolean }) {
  const current = ORDER.indexOf(phase);
  return (
    <ol className="research-steps">
      {STEPS.map((step) => {
        const index = ORDER.indexOf(step.phase);
        const state = index < current ? "done" : index === current ? "active" : "todo";
        return (
          <li key={step.phase} className={`step-${state}`}>
            <span className={state === "active" && live ? "shimmer" : undefined}>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Placeholder windows while the planner decides how to split the topic */
function PlanningCrew() {
  return (
    <div className="crew-grid">
      {[0, 1, 2].map((index) => (
        <div key={index} className="window window-placeholder" style={{ animationDelay: `${index * 160}ms` }}>
          <div className="window-bar">
            <span className="window-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          </div>
          <div className="window-viewport">
            <div className="screen screen-loading">
              {index === 1 && <span className="screen-message shimmer">Splitting the topic into angles</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

type Props = { state: ResearchState; live: boolean };

/** A /research run: the crew's windows while they work, then the cited report */
export const ResearchView = memo(function ResearchView({ state, live }: Props) {
  const { phase, agents } = state;
  const finished = phase === "done" || !live;
  const [focused, setFocused] = useState<string | null>(null);
  // The windows are the show while research runs; afterwards they fold away beneath the report's header
  const [showCrew, setShowCrew] = useState<boolean | null>(null);
  const crewOpen = showCrew ?? !finished;

  // The planner names the research; once the writer titles the report, that title takes over
  const title = parseReport(state.report).title ?? state.title;
  const now = useNow(live);
  const elapsed = (state.endedAt ?? (live ? now : state.startedAt)) - state.startedAt;
  const hues = useMemo(() => new Map(agents.map((agent, index) => [agent.plan.id, agentHue(index)])), [agents]);
  const plans = useMemo(() => agents.map((agent) => agent.plan), [agents]);

  const pages = agents.reduce((sum, agent) => sum + agent.pages.filter((page) => page.status === "loaded").length, 0);
  const notes = agents.reduce((sum, agent) => sum + agent.notes.length, 0);
  const stats = [
    agents.length > 0 && `${agents.length} agents`,
    pages > 0 && `${pages} pages read`,
    notes > 0 && `${notes} notes`,
    state.sources.length > 0 && `${state.sources.length} sources`,
    elapsed > 0 && clock(elapsed),
  ].filter(Boolean);

  return (
    <section className="research" aria-label={`Research: ${title ?? "planning"}`}>
      <header className="research-header">
        <div className="research-kicker">
          <span>Research</span>
          {live ? (
            <Steps phase={phase} live={live} />
          ) : (
            <span className="research-finished">{phase === "done" ? "Finished" : "Stopped"}</span>
          )}
        </div>
        <h1 key={title ?? "planning"} className="research-title materialize">
          {title ?? "Planning the research"}
        </h1>
        {stats.length > 0 && <p className="research-stats">{stats.join(" · ")}</p>}
      </header>

      {agents.length > 0 && finished && (
        <button type="button" className="crew-toggle quiet" onClick={() => setShowCrew(!crewOpen)} aria-expanded={crewOpen}>
          <span className="crew-avatars" aria-hidden="true">
            {agents.map((agent) => (
              <span key={agent.plan.id} className="crew-avatar" style={{ ["--hue" as string]: hues.get(agent.plan.id) }}>
                <PlatformIcon platform={agent.plan.platform} />
              </span>
            ))}
          </span>
          {crewOpen ? "Hide the agents" : "Show what the agents did"}
        </button>
      )}

      {crewOpen && (
        <div className="crew">
          {agents.length === 0 ? (
            live && <PlanningCrew />
          ) : (
            <div className="crew-grid">
              {agents.map((agent, index) => (
                <AgentWindow
                  key={agent.plan.id}
                  agent={agent}
                  hue={agentHue(index)}
                  live={live}
                  focused={focused === agent.plan.id}
                  onFocus={() => setFocused(focused === agent.plan.id ? null : agent.plan.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {phase === "writing" && !state.report && live && (
        <p className="research-writing">
          <span className="shimmer">Reading {notes} notes and writing the report</span>
        </p>
      )}

      {state.report && (
        <Report text={state.report} sources={state.sources} agents={plans} hues={hues} live={live && phase === "writing"} />
      )}

      {phase === "done" && !live && state.report && (
        <ExportBar
          report={{ title: title ?? "Research report", text: state.report, sources: state.sources, agents: agents.length, date: state.date }}
        />
      )}
    </section>
  );
});
