import { accessToken, claims, onAuthChange } from "./auth";
import { agentUrl, remote } from "./config";

/**
 * The WebSocket to the agent (agent/src/radagent/server/ws.py), kept open across sleeps, network changes and
 * AgentCore's one-hour connection limit. Chats live on the server, so a dropped connection loses nothing but the
 * events sent while it was down; useAgent reloads what it missed.
 *
 * AgentCore caps frames at 64 KB and 250 a second, so events arrive batched in JSON arrays, a large one arrives as
 * {"type": "part"} pieces, and large commands (prompts with files) go out the same way, paced
 */

/** What the connection itself reports, alongside the agent's own events */
export type ConnectionEvent =
  | { type: "starting" }
  | { type: "disconnected"; message: string }
  | { type: "signed-out" };

type Listener = (event: any) => void;

// Under AgentCore's 64 KB frame limit; see FRAME_LIMIT and PART_CHARS in ws.py
const FRAME_LIMIT = 48 * 1024;
const PART_CHARS = 24 * 1024;
// Frames a second, under AgentCore's 250
const FRAMES_PER_SECOND = 120;
const BEARER_PROTOCOL = "base64UrlBearerAuthorization";
// Seconds to wait before each retry; the last repeats
const BACKOFF_S = [0.5, 1, 2, 5, 10, 20, 30];
// Commands sent while offline wait for the connection, up to this many
const MAX_QUEUED = 50;

/** JSON with everything outside ASCII escaped, so its length in characters is its length in bytes */
function asciiJson(value: unknown): string {
  return JSON.stringify(value).replace(/[\u007f-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}

function base64Url(text: string): string {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

class Connection {
  private socket: WebSocket | null = null;
  private connecting = false;
  private attempt = 0;
  /** Connections that closed before they opened in a row; a rejected token looks like this */
  private failedOpens = 0;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private listeners = new Set<Listener>();
  private queued: string[] = [];
  private outgoing: string[] = [];
  private pumping = false;
  private parts = new Map<string, (string | undefined)[]>();
  private started = false;

  /** Receive every event; the first subscriber opens the connection */
  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    if (!this.started) this.start();
    return () => this.listeners.delete(listener);
  }

  /** Send a command now, or as soon as the connection is back */
  send(command: Record<string, unknown>): void {
    const message = asciiJson(command);
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.write(message);
      return;
    }
    if (this.queued.length >= MAX_QUEUED) throw new Error("Not connected to the agent.");
    this.queued.push(message);
    this.connectSoon();
  }

  /** Drop the connection and open a new one right away */
  reconnect(): void {
    this.socket?.close();
    this.connectSoon(true);
  }

  private start(): void {
    this.started = true;
    // Coming back to the app or the network is the moment to reconnect, not whenever the backoff says
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") this.connectSoon(true);
    });
    window.addEventListener("online", () => this.connectSoon(true));
    onAuthChange((signedIn) => {
      if (signedIn) this.connectSoon(true);
      else this.socket?.close();
    });
    void this.connect();
  }

  private emit(event: unknown): void {
    this.listeners.forEach((listener) => listener(event));
  }

  private connectSoon(now = false): void {
    if (this.socket || this.connecting) return;
    clearTimeout(this.retry);
    const delay = now ? 0 : BACKOFF_S[Math.min(this.attempt, BACKOFF_S.length - 1)] * 1000;
    this.retry = setTimeout(() => void this.connect(), delay);
  }

  private async connect(): Promise<void> {
    if (this.socket || this.connecting) return;
    this.connecting = true;
    this.emit({ type: "starting" });

    let token: string | null;
    try {
      // Two failed opens in a row: the token may have been rejected, so get a fresh one
      token = await accessToken({ force: this.failedOpens >= 2 });
    } catch (error) {
      this.connecting = false;
      this.attempt += 1;
      this.emit({ type: "disconnected", message: `Can't reach sign-in: ${String(error)}` });
      this.connectSoon();
      return;
    }
    if (token === null) {
      // Signing in calls onAuthChange, which connects again
      this.connecting = false;
      this.emit({ type: "signed-out" });
      return;
    }

    const session = remote ? `radagent-${claims(token).sub}` : undefined;
    const protocols = remote ? [`${BEARER_PROTOCOL}.${base64Url(token)}`, BEARER_PROTOCOL] : undefined;
    let opened = false;
    let socket: WebSocket;
    try {
      socket = new WebSocket(agentUrl(session), protocols);
    } catch (error) {
      this.connecting = false;
      this.emit({ type: "disconnected", message: String(error) });
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      opened = true;
      this.connecting = false;
      this.attempt = 0;
      this.failedOpens = 0;
      const queued = this.queued;
      this.queued = [];
      queued.forEach((message) => this.write(message));
    };
    socket.onmessage = (message) => this.receive(message.data);
    socket.onclose = (close) => {
      if (this.socket === socket) this.socket = null;
      this.connecting = false;
      this.outgoing = [];
      this.parts.clear();
      if (opened) {
        // Usually AgentCore's hourly limit or the phone sleeping; come straight back
        this.attempt = 0;
      } else {
        this.attempt += 1;
        this.failedOpens += 1;
      }
      const why = close.reason || (opened ? "Connection lost" : "Can't reach the agent");
      this.emit({ type: "disconnected", message: `${why}. Reconnecting…` });
      this.connectSoon();
    };
  }

  private receive(data: unknown): void {
    if (typeof data !== "string") return;
    let message: any;
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    if (Array.isArray(message)) {
      message.forEach((event) => this.emit(event));
    } else if (message?.type === "part") {
      const slices = this.parts.get(message.id) ?? new Array(message.of).fill(undefined);
      slices[message.n] = message.data;
      this.parts.set(message.id, slices);
      if (slices.every((slice) => slice !== undefined)) {
        this.parts.delete(message.id);
        try {
          this.emit(JSON.parse(slices.join("")));
        } catch {
          // A broken message is dropped like any unreadable one
        }
      }
    } else if (message) {
      this.emit(message);
    }
  }

  /** Queue a message as one frame, or as parts when it's too large for one */
  private write(message: string): void {
    if (message.length <= FRAME_LIMIT) {
      this.outgoing.push(message);
    } else {
      const id = crypto.randomUUID().replace(/-/g, "");
      const of = Math.ceil(message.length / PART_CHARS);
      for (let n = 0; n < of; n++) {
        this.outgoing.push(JSON.stringify({ type: "part", id, n, of, data: message.slice(n * PART_CHARS, (n + 1) * PART_CHARS) }));
      }
    }
    void this.pump();
  }

  /** Send queued frames no faster than FRAMES_PER_SECOND */
  private async pump(): Promise<void> {
    if (this.pumping) return;
    this.pumping = true;
    try {
      let sent = 0;
      let windowStart = performance.now();
      while (this.outgoing.length && this.socket?.readyState === WebSocket.OPEN) {
        if (sent >= FRAMES_PER_SECOND) {
          const wait = 1000 - (performance.now() - windowStart);
          if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
          sent = 0;
          windowStart = performance.now();
          continue;
        }
        this.socket.send(this.outgoing.shift()!);
        sent += 1;
      }
    } finally {
      this.pumping = false;
    }
  }
}

/** The app's one connection to the agent */
export const connection = new Connection();
