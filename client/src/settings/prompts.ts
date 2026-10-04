import { useSyncExternalStore } from "react";
import { connection } from "../remote/connection";

/**
 * The agent's system prompt presets, which live with the agent (agent/src/radagent/prompts/presets.py) so every
 * device shares them. Plain TypeScript like the settings store; `usePrompts()` is the React binding
 */

export type PromptSlot = { name: string; text: string };
export type PromptPresets = { active: number; slots: PromptSlot[] };

/** What the agent sends about prompts; see dispatch() in agent/src/radagent/server/core.py */
export type PromptEvent = ({ type: "prompts" } & PromptPresets) | { type: "prompt_error"; message: string };

type State = {
  /** Undefined until the agent has sent them */
  presets?: PromptPresets;
  /** Why the last change didn't go through */
  error?: string;
  /** A change was sent and the agent hasn't answered yet */
  saving: boolean;
};

let state: State = { saving: false };
const listeners = new Set<() => void>();
let unsubscribe: (() => void) | undefined;

function update(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener());
}

function send(command: Record<string, unknown>) {
  try {
    connection.send(command);
  } catch (error) {
    update({ saving: false, error: String(error) });
  }
}

/** Listen for the agent's prompt events and ask for the presets; again on every reconnect, since they may have changed */
function listen() {
  if (unsubscribe) return;
  unsubscribe = connection.subscribe((event: { type: string } & Record<string, unknown>) => {
    if (event.type === "ready") send({ type: "prompts" });
    else if (event.type === "prompts") {
      const { active, slots } = event as Extract<PromptEvent, { type: "prompts" }>;
      update({ presets: { active, slots }, saving: false, error: undefined });
    } else if (event.type === "prompt_error") update({ saving: false, error: String(event.message) });
  });
  send({ type: "prompts" });
}

export const prompts = {
  get: (): State => state,

  subscribe(listener: () => void) {
    listen();
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },

  /** Replace a slot's prompt; empty text empties the slot */
  save(slot: number, name: string, text: string) {
    update({ saving: true, error: undefined });
    send({ type: "save_prompt", slot, name, text });
  },

  /** Run every chat with this slot's prompt */
  use(slot: number) {
    if (state.presets?.active === slot) return;
    update({ saving: true, error: undefined });
    send({ type: "use_prompt", slot });
  },
};

/**
 * The presets, re-rendering when they change. The agent sends them to every device whenever one changes them, and
 * they're asked for again on every reconnect, so what's here stays current
 */
export function usePrompts() {
  return useSyncExternalStore(prompts.subscribe, prompts.get);
}

/** How a slot is labelled: its name, or its number */
export function slotLabel(slot: PromptSlot | undefined, index: number): string {
  if (slot?.name) return slot.name;
  return slot?.text ? `Prompt ${index + 1}` : "Empty";
}
