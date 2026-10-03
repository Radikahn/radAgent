import { memo, useState } from "react";
import type { Part, Turn } from "../agent";
import { CardView } from "../cards";
import { CommandPartView } from "./CommandPart";
import { Attachments } from "./Attachments";
import { MagicText } from "./MagicText";

// What each tool is doing while it runs and once it's done; unknown tools fall back to their name
const TOOL_LABELS: Record<string, [string, string]> = {
  web_search: ["Searching the web", "Searched the web"],
  read_page: ["Reading", "Read"],
  find_places: ["Looking up places", "Looked up places"],
  shell: ["Running", "Ran"],
  read: ["Reading", "Read"],
  write: ["Writing", "Wrote"],
  edit: ["Editing", "Edited"],
  subagent: ["Delegating", "Delegated"],
  programmatic_tool_caller: ["Running code", "Ran code"],
  todo_write: ["Planning", "Planned"],
  search_memory: ["Remembering", "Remembered"],
  search_chats: ["Looking through other chats", "Looked through other chats"],
  read_chat: ["Reading another chat", "Read another chat"],
  share_links: ["Sharing links", "Shared links"],
  search_youtube: ["Searching YouTube", "Searched YouTube"],
};

type Tool = Extract<Part, { kind: "tool" }>;
type Step = Extract<Part, { kind: "thinking" | "tool" }>;

const isStep = (part: Part): part is Step => part.kind === "thinking" || part.kind === "tool";

const toolLabels = (tool: Tool) => TOOL_LABELS[tool.name] ?? [`Using ${tool.name}`, `Used ${tool.name}`];

const seconds = (ms: number) => Math.max(1, Math.round(ms / 1000));

/** How long the agent spent on its steps, for once it has stopped working */
function summary(steps: Step[]): string {
  if (steps.every((step) => step.kind === "thinking")) {
    const thought = steps.reduce((ms, step) => ms + (step.endedAt ?? step.startedAt) - step.startedAt, 0);
    return thought ? `Thought for ${seconds(thought)}s` : "Thought";
  }
  const start = Math.min(...steps.map((step) => step.startedAt));
  const end = Math.max(...steps.map((step) => step.endedAt ?? step.startedAt));
  // Turns reopened from a saved chat have no timings
  return end > start ? `Worked for ${seconds(end - start)}s` : "Worked";
}

/** What the activity line reads: the step in progress while working, otherwise a summary */
function status(steps: Step[], live: boolean, writing: boolean): { label: string; detail?: string; moving: boolean } {
  if (live) {
    const running = steps.filter((step): step is Tool => step.kind === "tool" && step.status === "running").pop();
    if (running) return { label: toolLabels(running)[0], detail: running.detail, moving: true };
    const latest = steps[steps.length - 1];
    if (latest.kind === "thinking" && latest.endedAt === undefined) return { label: "Thinking", moving: true };
    // Between steps nothing else is moving, so the line keeps shimmering to show the agent is still at work
    if (!writing) return { label: "Working", moving: true };
  }
  return { label: summary(steps), moving: false };
}

function ToolLine({ tool, live }: { tool: Tool; live: boolean }) {
  const [active, done] = toolLabels(tool);
  const running = live && tool.status === "running";
  return (
    <div className={`tool materialize ${tool.status === "error" ? "failed" : ""}`}>
      <span className={running ? "shimmer" : undefined}>{running ? active : done}</span>
      {tool.detail && <span className="tool-detail">{tool.detail}</span>}
    </div>
  );
}

/** One line for all of a turn's thinking and tool calls, updating in place; it opens to the full list of steps */
function Activity({ steps, live, writing }: { steps: Step[]; live: boolean; writing: boolean }) {
  const [open, setOpen] = useState(false);
  const { label, detail, moving } = status(steps, live, writing);
  return (
    <div className="activity">
      <button type="button" className="quiet activity-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        {/* Keyed so each new label condenses in, rather than swapping abruptly */}
        <span key={label} className="activity-label materialize">
          <span className={moving ? "shimmer" : undefined}>{label}</span>
        </span>
        {detail && (
          <span key={detail} className="tool-detail materialize">
            {detail}
          </span>
        )}
      </button>
      {open && (
        <div className="activity-steps">
          {steps.map((step, index) =>
            step.kind === "thinking" ? (
              <p key={index}>{step.text}</p>
            ) : (
              <ToolLine key={index} tool={step} live={live} />
            ),
          )}
        </div>
      )}
    </div>
  );
}

function PartView({ part, live }: { part: Part; live: boolean }) {
  switch (part.kind) {
    case "text":
      return <MagicText text={part.text} live={live} />;
    case "card":
      return (
        <div className="materialize">
          <CardView card={part.card} />
        </div>
      );
    case "command":
      return <CommandPartView command={part.command} state={part.state} live={live} />;
    default:
      // Thinking and tool calls show in the turn's activity line
      return null;
  }
}

export const TurnView = memo(function TurnView({ turn }: { turn: Turn }) {
  const streaming = turn.status === "streaming";
  const steps = turn.parts.filter(isStep);
  // The activity line sits where the first step arrived; text written between later steps flows in below it
  const firstStep = turn.parts.findIndex(isStep);
  const last = turn.parts[turn.parts.length - 1];
  // Before any text or steps arrive nothing else is moving, so a soft pulse shows the agent is at work
  const waiting = streaming && !steps.length && (!last || last.kind === "card");

  return (
    <section className="turn">
      {!!turn.attachments?.length && <Attachments className="prompt-attachments" files={turn.attachments} />}
      {/* Files can be sent without a message, leaving nothing for the bubble to hold */}
      {(turn.prompt || turn.command) && (
        <div className="prompt">
          {turn.command && <span className="prompt-command">/{turn.command}</span>}
          {turn.prompt}
        </div>
      )}
      <div className="reply">
        {turn.parts.map((part, index) =>
          // Parts only ever append, so the index is a stable key
          index === firstStep ? (
            <Activity key={index} steps={steps} live={streaming} writing={last.kind === "text"} />
          ) : (
            <PartView key={index} part={part} live={streaming && index === turn.parts.length - 1} />
          ),
        )}
        {waiting && <div className="pulse" role="status" aria-label="Working" />}
        {turn.status === "stopped" && <p className="turn-note">Stopped</p>}
        {turn.error && <p className="turn-note failed">{turn.error}</p>}
      </div>
    </section>
  );
});
