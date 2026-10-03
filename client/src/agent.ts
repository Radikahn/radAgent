import { useCallback, useEffect, useMemo, useReducer } from "react";
import { encode, type Attachment, type PendingFile } from "./chat/files";
import { reduceCommand, replayCommand } from "./chat/CommandPart";
import { connection, type ConnectionEvent } from "./remote/connection";

/** A chat as the sidebar lists it; chats live in agent/.agent/chats, see agent/src/radagent/chats.py */
export type ChatSummary = { id: string; title: string; created_at: string; updated_at: string };

/**
 * Everything the agent sends, plus what the connection reports (remote/connection.ts); the protocol lives in
 * agent/src/radagent/server/core.py
 */
export type AgentEvent =
  | ConnectionEvent
  | { type: "ready" }
  | { type: "chats"; chats: ChatSummary[] }
  /** `running`: a turn is still being answered, so the last saved turn isn't finished */
  | { type: "history"; chat: string; turns: Turn[]; running?: boolean }
  /** A turn started, possibly on another device */
  | { type: "turn_start"; chat: string; turn: string; text: string; command: string | null; attachments: string[] }
  | { type: "error"; message: string; chat?: string; turn?: string }
  | { type: "text" | "thinking"; chat: string; turn: string; delta: string }
  | { type: "tool_start"; chat: string; turn: string; id: string; name: string }
  | { type: "tool_input"; chat: string; turn: string; id: string; detail: string }
  | { type: "tool_end"; chat: string; turn: string; id: string; status: "success" | "error" }
  | { type: "card"; chat: string; turn: string; id: string; card: unknown }
  | { type: "command_event"; chat: string; turn: string; command: string; event: unknown }
  | { type: "turn_end"; chat: string; turn: string; stop_reason: string };

/** One piece of a reply, kept in the order it streamed in */
export type Part =
  | { kind: "text"; text: string }
  | { kind: "thinking"; text: string; startedAt: number; endedAt?: number }
  | {
      kind: "tool";
      id: string;
      name: string;
      detail: string;
      status: "running" | "success" | "error";
      startedAt: number;
      endedAt?: number;
    }
  | { kind: "card"; id: string; card: unknown }
  /** A slash command's live part, e.g. /research's agent windows and report; see chat/CommandPart.tsx */
  | { kind: "command"; command: string; state: unknown };

export type Turn = {
  id: string;
  prompt: string;
  /** The slash command the message was sent with, e.g. "memory" */
  command?: string;
  /** Files sent with the message */
  attachments?: Attachment[];
  parts: Part[];
  status: "streaming" | "done" | "stopped" | "failed";
  error?: string;
  /** Some of its events were missed while offline, so the saved version replaces it once it ends */
  stale?: boolean;
};

export type AgentStatus = "starting" | "ready" | "stopped" | "signed-out";

type State = {
  status: AgentStatus;
  chats: ChatSummary[];
  /** The chat on screen; a new chat isn't in `chats` until its first message */
  activeId: string;
  /** The turns of each chat opened since the app started; a chat whose history is still loading has none */
  threads: Record<string, Turn[]>;
  notice?: string;
  /** Chats whose next history replaces what's on hand, because events were missed */
  reload: string[];
  /** Chats whose last turn was still running when their history loaded; the next unknown turn id is that turn's */
  adopt: string[];
};

type Action =
  | { kind: "event"; event: AgentEvent; at: number }
  | { kind: "submit"; chat: string; turn: Turn }
  | { kind: "fail"; chat: string; turn: string; error: string }
  | { kind: "open"; chat: string; isNew?: boolean }
  | { kind: "remove"; chat: string; next: string };

/** Ids are made here so a new chat costs nothing until its first message; the agent accepts [a-z0-9]{6,32} */
const newChatId = () => crypto.randomUUID().replace(/-/g, "").slice(0, 12);

function updateTurn(state: State, chat: string, id: string, update: (turn: Turn) => Turn): State {
  const turns = state.threads[chat];
  // Events for a chat that's gone (deleted) are dropped
  if (!turns) return state;
  return { ...state, threads: { ...state.threads, [chat]: turns.map((turn) => (turn.id === id ? update(turn) : turn)) } };
}

/** Thinking ends when anything else starts; stamping it then gives "Thought for Ns" */
function endThinking(parts: Part[], at: number): Part[] {
  return parts.map((part) => (part.kind === "thinking" && part.endedAt === undefined ? { ...part, endedAt: at } : part));
}

function updateTool(parts: Part[], id: string, update: Partial<Extract<Part, { kind: "tool" }>>): Part[] {
  return parts.map((part) => (part.kind === "tool" && part.id === id ? { ...part, ...update } : part));
}

function applyPart(parts: Part[], event: AgentEvent, at: number): Part[] {
  const last = parts[parts.length - 1];
  switch (event.type) {
    case "text":
      if (last?.kind === "text") return [...parts.slice(0, -1), { ...last, text: last.text + event.delta }];
      return [...endThinking(parts, at), { kind: "text", text: event.delta }];
    case "thinking":
      if (last?.kind === "thinking") return [...parts.slice(0, -1), { ...last, text: last.text + event.delta }];
      return [...parts, { kind: "thinking", text: event.delta, startedAt: at }];
    case "tool_start":
      return [
        ...endThinking(parts, at),
        { kind: "tool", id: event.id, name: event.name, detail: "", status: "running", startedAt: at },
      ];
    case "tool_input":
      return updateTool(parts, event.id, { detail: event.detail });
    case "tool_end":
      return updateTool(parts, event.id, { status: event.status, endedAt: at });
    case "card":
      return [...parts, { kind: "card", id: event.id, card: event.card }];
    case "command_event": {
      // All of a command's events build up one part
      const index = parts.findIndex((part) => part.kind === "command" && part.command === event.command);
      if (index < 0) {
        return [...parts, { kind: "command", command: event.command, state: reduceCommand(event.command, undefined, event.event, at) }];
      }
      return parts.map((part, i) =>
        i === index && part.kind === "command" ? { ...part, state: reduceCommand(part.command, part.state, event.event, at) } : part,
      );
    }
    default:
      return parts;
  }
}

/** A saved turn as the client keeps it: a command's part arrives as its saved events and is replayed into state */
function restoreTurn(turn: Turn): Turn {
  if (!turn.parts.some((part) => part.kind === "command")) return turn;
  const parts = turn.parts.map((part) => {
    if (part.kind !== "command" || !("events" in part)) return part;
    const { events, ...rest } = part as typeof part & { events: unknown };
    return { ...rest, state: replayCommand(part.command, events) };
  });
  return { ...turn, parts };
}

/** Mark the replies still coming in as missing events; the connection dropped under them */
function markStale(threads: Record<string, Turn[]>): Record<string, Turn[]> {
  return Object.fromEntries(
    Object.entries(threads).map(([chat, turns]) => [
      chat,
      turns.map((turn) => (turn.status === "streaming" ? { ...turn, stale: true } : turn)),
    ]),
  );
}

/** A chat's saved turns, keeping the replies this device is following live that aren't saved yet */
function loadHistory(state: State, event: Extract<AgentEvent, { type: "history" }>): State {
  const saved = event.turns.map(restoreTurn);
  const ids = new Set(saved.map((turn) => turn.id));
  const live = (state.threads[event.chat] ?? []).filter((turn) => turn.status === "streaming" && !turn.stale && !ids.has(turn.id));
  let adopt = state.adopt.filter((chat) => chat !== event.chat);
  if (event.running && !live.length && saved.length) {
    // The reply is running on the server, started on another device or before this one reconnected
    saved[saved.length - 1] = { ...saved[saved.length - 1], status: "streaming", stale: true };
    adopt = [...adopt, event.chat];
  }
  return {
    ...state,
    adopt,
    reload: state.reload.filter((chat) => chat !== event.chat),
    threads: { ...state.threads, [event.chat]: [...saved, ...live] },
  };
}

/** The turn an event is for: a running turn from saved history takes the id the server streams it under */
function claimTurn(state: State, chat: string, id: string): State {
  const turns = state.threads[chat];
  if (!turns || turns.some((turn) => turn.id === id) || !state.adopt.includes(chat)) return state;
  const last = turns[turns.length - 1];
  return {
    ...state,
    adopt: state.adopt.filter((other) => other !== chat),
    threads: { ...state.threads, [chat]: [...turns.slice(0, -1), { ...last, id }] },
  };
}

function applyEvent(state: State, event: AgentEvent, at: number): State {
  switch (event.type) {
    case "starting":
      return { ...state, status: "starting" };
    case "ready":
      // Whatever happened while offline is in the saved history; the hook asks for the chat on screen again
      return { ...state, status: "ready", notice: undefined, reload: [...new Set([...state.reload, state.activeId])] };
    case "disconnected":
      return { ...state, status: "starting", notice: event.message, threads: markStale(state.threads) };
    case "signed-out":
      return { ...state, status: "signed-out", notice: undefined };
    case "chats":
      return { ...state, chats: event.chats };
    case "history":
      // A chat already on hand is at least as current as what's saved, e.g. a reply still streaming, unless it missed
      // events while offline
      if (state.threads[event.chat] && !state.reload.includes(event.chat)) return state;
      return loadHistory(state, event);
    case "turn_start": {
      const turns = state.threads[event.chat];
      // The device that sent it already shows it; a chat that isn't loaded gets it with its history
      if (!turns || turns.some((turn) => turn.id === event.turn)) return state;
      const attachments = event.attachments.map((name) => ({ name, kind: "document" as const }));
      const turn: Turn = { id: event.turn, prompt: event.text, command: event.command ?? undefined, attachments, parts: [], status: "streaming" };
      return { ...state, threads: { ...state.threads, [event.chat]: [...turns, turn] } };
    }
    case "error":
      if (event.chat && event.turn) {
        return updateTurn(state, event.chat, event.turn, (turn) => ({ ...turn, error: event.message }));
      }
      return { ...state, notice: event.message };
    case "turn_end": {
      const claimed = claimTurn(state, event.chat, event.turn);
      const stale = claimed.threads[event.chat]?.find((turn) => turn.id === event.turn)?.stale;
      // A reply that missed events is shown complete from the saved conversation instead
      const next = stale ? { ...claimed, reload: [...new Set([...claimed.reload, event.chat])] } : claimed;
      return updateTurn(next, event.chat, event.turn, (turn) => ({
        ...turn,
        parts: endThinking(turn.parts, at),
        status:
          event.stop_reason === "cancelled"
            ? "stopped"
            : event.stop_reason === "error" || event.stop_reason === "rejected"
              ? "failed"
              : "done",
      }));
    }
    default: {
      const claimed = claimTurn(state, event.chat, event.turn);
      return updateTurn(claimed, event.chat, event.turn, (turn) => ({ ...turn, parts: applyPart(turn.parts, event, at) }));
    }
  }
}

function reduce(state: State, action: Action): State {
  switch (action.kind) {
    case "event":
      return applyEvent(state, action.event, action.at);
    case "submit": {
      const turns = state.threads[action.chat] ?? [];
      return { ...state, notice: undefined, threads: { ...state.threads, [action.chat]: [...turns, action.turn] } };
    }
    case "fail":
      return updateTurn(state, action.chat, action.turn, (turn) => ({ ...turn, status: "failed", error: action.error }));
    case "open": {
      // A new chat has nothing to load, so it starts empty instead of waiting for its history
      const threads = action.isNew ? { ...state.threads, [action.chat]: [] } : state.threads;
      return { ...state, notice: undefined, activeId: action.chat, threads };
    }
    case "remove": {
      const { [action.chat]: _removed, ...threads } = state.threads;
      const chats = state.chats.filter((chat) => chat.id !== action.chat);
      if (state.activeId !== action.chat) return { ...state, chats, threads };
      return { ...state, chats, activeId: action.next, threads: { ...threads, [action.next]: [] } };
    }
  }
}

function sendCommand(command: Record<string, unknown>): Promise<void> {
  try {
    connection.send(command);
    return Promise.resolve();
  } catch (error) {
    return Promise.reject(error);
  }
}

function initialState(): State {
  const activeId = newChatId();
  return { status: "starting", chats: [], activeId, threads: { [activeId]: [] }, reload: [], adopt: [] };
}

/** Chats with the agent, on AWS or on this machine (see remote/config.ts), plus the commands that drive them */
export function useAgent() {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const { activeId, threads } = state;

  // The server lists the chats by itself on connecting; `ready` puts the chat on screen up for reloading below, which
  // also tells the server which chat this device is showing
  useEffect(() => connection.subscribe((event: AgentEvent) => dispatch({ kind: "event", event, at: Date.now() })), []);

  // A chat that missed events while offline: the one on screen is fetched again now, the others when next opened
  useEffect(() => {
    for (const chat of state.reload) {
      if (chat === activeId) sendCommand({ type: "open", chat }).catch(() => {});
    }
  }, [state.reload, activeId]);

  const send = useCallback(
    (text: string, command?: string, files: PendingFile[] = []) => {
      const attachments = files.map(({ name, kind, preview }) => ({ name, kind, preview }));
      const turn: Turn = { id: crypto.randomUUID(), prompt: text, command, attachments, parts: [], status: "streaming" };
      dispatch({ kind: "submit", chat: activeId, turn });
      // Files travel as base64 inside the command; reading them takes a moment, so the turn shows first
      Promise.all(files.map(async (file) => ({ name: file.name, data: await encode(file.file) })))
        .then((encoded) =>
          sendCommand({ type: "prompt", chat: activeId, turn: turn.id, text, command, attachments: encoded }),
        )
        .catch((error) => dispatch({ kind: "fail", chat: activeId, turn: turn.id, error: String(error) }));
    },
    [activeId],
  );

  const stop = useCallback(() => {
    sendCommand({ type: "cancel", chat: activeId }).catch(() => {});
  }, [activeId]);

  const openChat = useCallback((chat: string) => {
    dispatch({ kind: "open", chat });
    // Also tells the agent which chat is on screen, so it can unload the others once they're idle
    sendCommand({ type: "open", chat }).catch(() => {});
  }, []);

  const newChat = useCallback(() => {
    const chat = newChatId();
    dispatch({ kind: "open", chat, isNew: true });
    sendCommand({ type: "open", chat }).catch(() => {});
  }, []);

  const deleteChat = useCallback(
    (chat: string) => {
      const next = newChatId();
      dispatch({ kind: "remove", chat, next });
      sendCommand({ type: "delete", chat }).catch(() => {});
      if (chat === activeId) sendCommand({ type: "open", chat: next }).catch(() => {});
    },
    [activeId],
  );

  const restart = useCallback(() => connection.reconnect(), []);

  // Chats whose latest reply is still coming in, so the sidebar can show they're busy
  const answering = useMemo(
    () =>
      new Set(
        Object.entries(threads)
          .filter(([, turns]) => turns[turns.length - 1]?.status === "streaming")
          .map(([chat]) => chat),
      ),
    [threads],
  );

  return {
    status: state.status,
    signedOut: state.status === "signed-out",
    chats: state.chats,
    notice: state.notice,
    activeId,
    turns: threads[activeId] ?? [],
    loading: threads[activeId] === undefined,
    answering,
    send,
    stop,
    openChat,
    newChat,
    deleteChat,
    restart,
  };
}
