import type { ReactNode } from "react";
import { reduceResearch, type ResearchState } from "../research/state";
import { ResearchView } from "../research/ResearchView";

/**
 * A slash command's part of a reply: its `command_event`s fold into state that its own view renders. Like cards,
 * a command this client doesn't know renders nothing; see agent/src/radagent/commands.py for the agent side
 */
type Renderer<S> = {
  reduce: (state: S | undefined, event: unknown, at: number) => S;
  View: (props: { state: S; live: boolean }) => ReactNode;
};

const RENDERERS: Record<string, Renderer<any>> = {
  research: { reduce: reduceResearch, View: ResearchView } satisfies Renderer<ResearchState>,
};

/** Folds one of a command's events into its part's state */
export function reduceCommand(command: string, state: unknown, event: unknown, at: number): unknown {
  const renderer = RENDERERS[command];
  return renderer ? renderer.reduce(state, event, at) : state;
}

/**
 * A reopened chat sends a command's saved events rather than its state, each with the seconds since the command
 * started; replaying them rebuilds the state, timings included
 */
export function replayCommand(command: string, events: unknown): unknown {
  if (!Array.isArray(events)) return undefined;
  return events.reduce<unknown>((state, saved: { t?: unknown; event?: unknown }) => {
    const at = typeof saved?.t === "number" ? saved.t * 1000 : 0;
    return reduceCommand(command, state, saved?.event, at);
  }, undefined);
}

export function CommandPartView({ command, state, live }: { command: string; state: unknown; live: boolean }) {
  const renderer = RENDERERS[command];
  if (!renderer || state === undefined) return null;
  return <renderer.View state={state} live={live} />;
}
