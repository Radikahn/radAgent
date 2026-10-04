import { isTauri } from "@tauri-apps/api/core";
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import { openUrl } from "@tauri-apps/plugin-opener";
import { googleClientId } from "./config";
import { connection } from "./connection";

/**
 * Connecting the agent to the user's Google account (Drive, Docs, Calendar), from Settings
 *
 * The app runs Google's consent page in the browser with PKCE, as an iOS-type OAuth client (which has no secret), and
 * Google sends the browser back to the client's own scheme, com.googleusercontent.apps.<id>:/oauth2redirect. The
 * deep-link plugin hands that address to the app (scripts/install-*.sh register the scheme); where it can't, e.g. a
 * development build on macOS, the address can be pasted into Settings instead. Either way the code and its verifier
 * go to the agent (agent/src/radagent/server/google.py), which trades them for the refresh token and keeps it, so
 * the token never stays on a device
 */
const SCOPES = [
  "openid",
  "email",
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/documents",
  "https://www.googleapis.com/auth/calendar",
];
const AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth";
// The consent in progress; kept in localStorage so it survives iOS ending the app while Safari is in front
const PENDING_KEY = "radagent.google-pending";
// An unanswered consent is dropped after this long
const PENDING_TTL_MS = 15 * 60 * 1000;

/** The agent's `google` event */
export type GoogleStatus = {
  connected: boolean;
  email?: string;
  connected_at?: string;
  /** Scopes the user unticked on the consent page */
  missing?: string[];
  error?: string;
};

/** Where this device is in connecting: idle, waiting for the browser to come back, or handing the code to the agent */
export type GoogleStep = "idle" | "waiting" | "connecting";

type Pending = { state: string; verifier: string; at: number };

/** Whether this build knows its Google client (VITE_GOOGLE_CLIENT_ID); without one there's nothing to connect with */
export const googleConfigured = Boolean(googleClientId);

export const googleRedirectUri = googleConfigured
  ? `com.googleusercontent.apps.${googleClientId.replace(/\.apps\.googleusercontent\.com$/, "")}:/oauth2redirect`
  : "";

export type GoogleState = { status: GoogleStatus | null; step: GoogleStep; problem: string };

let status: GoogleStatus | null = null;
let step: GoogleStep = "idle";
let problem = "";
let snapshot: GoogleState = { status, step, problem };
const listeners = new Set<() => void>();

function changed(): void {
  snapshot = { status, step, problem };
  listeners.forEach((listener) => listener());
}

/** The agent's latest status, this device's step and its last error; the same object until one changes */
export function googleState(): GoogleState {
  return snapshot;
}

export function onGoogleChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function fail(message: string): void {
  step = "idle";
  problem = message;
  changed();
}

/** Ask the agent whether Google is connected; the answer arrives as a `google` event */
export function refreshGoogle(): void {
  try {
    connection.send({ type: "google_status" });
  } catch {
    // Offline; Settings asks again when it next opens
  }
}

export function disconnectGoogle(): void {
  try {
    connection.send({ type: "google_disconnect" });
    problem = "";
  } catch (error) {
    problem = String(error);
  }
  changed();
}

/** Stop waiting for a consent that isn't coming back */
export function cancelGoogle(): void {
  clearPending();
  step = "idle";
  problem = "";
  changed();
}

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function random(bytes: number): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(bytes)));
}

function readPending(): Pending | null {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_KEY) ?? "null") as Pending | null;
    return pending && Date.now() - pending.at < PENDING_TTL_MS ? pending : null;
  } catch {
    return null;
  }
}

function clearPending(): void {
  try {
    localStorage.removeItem(PENDING_KEY);
  } catch {
    // Nothing to clear
  }
}

/** Open Google's consent page; the browser comes back to the app through the redirect */
export async function connectGoogle(): Promise<void> {
  if (!googleConfigured) return;
  const verifier = random(48);
  const challenge = base64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
  const pending: Pending = { state: random(24), verifier, at: Date.now() };
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  } catch {
    fail("Couldn't keep track of the sign-in on this device.");
    return;
  }
  const url = new URL(AUTHORIZE_URL);
  url.search = new URLSearchParams({
    client_id: googleClientId,
    redirect_uri: googleRedirectUri,
    response_type: "code",
    scope: SCOPES.join(" "),
    state: pending.state,
    code_challenge: challenge,
    code_challenge_method: "S256",
    // A refresh token every time, so connecting again (say, with more boxes ticked) replaces the old login
    access_type: "offline",
    prompt: "consent",
  }).toString();

  problem = "";
  step = "waiting";
  changed();
  try {
    if (isTauri()) await openUrl(url.toString());
    else window.open(url.toString(), "_blank", "noopener");
  } catch (error) {
    fail(`Couldn't open the browser: ${String(error)}`);
  }
}

/**
 * Finish connecting with the address Google sent the browser back to; false when it isn't that address at all, so a
 * deep link meant for something else is left alone
 */
export function finishGoogle(address: string): boolean {
  if (!googleConfigured) return false;
  let url: URL;
  try {
    url = new URL(address.trim());
  } catch {
    return false;
  }
  // URL lowercases the scheme
  if (`${url.protocol}${url.pathname}` !== googleRedirectUri.toLowerCase()) return false;

  const pending = readPending();
  const params = url.searchParams;
  if (!pending || params.get("state") !== pending.state) {
    // Not the consent this device started (or it's too old), so its code can't be trusted
    fail("That sign-in wasn't started here or has expired. Press Connect again.");
    return true;
  }
  clearPending();
  const code = params.get("code");
  if (!code) {
    const error = params.get("error");
    fail(error === "access_denied" ? "Google access wasn't allowed." : `Google said: ${error ?? "no code"}.`);
    return true;
  }
  step = "connecting";
  problem = "";
  changed();
  try {
    connection.send({
      type: "google_connect",
      code,
      verifier: pending.verifier,
      redirect_uri: googleRedirectUri,
      client_id: googleClientId,
    });
  } catch (error) {
    fail(String(error));
  }
  return true;
}

let listening = false;

/** Catch Google's redirect and the agent's answers for the life of the app; main.tsx starts it */
export function listenForGoogle(): void {
  if (listening) return;
  listening = true;
  connection.subscribe((event) => {
    if (event?.type !== "google") return;
    const { type: _, ...rest } = event as GoogleStatus & { type: string };
    status = rest;
    // The answer to this device's connect (or to a disconnect) ends whatever it was doing
    if (step === "connecting" || rest.error) {
      step = "idle";
      problem = rest.error ?? "";
    }
    changed();
  });
  if (!googleConfigured || !isTauri()) return;
  const take = (urls: string[] | null) => urls?.forEach((url) => finishGoogle(url));
  // A redirect that launched the app arrives before anything listens, so ask for it too; the plugin keeps returning
  // the last one on later launches, so only while a consent is open
  getCurrent()
    .then((urls) => readPending() && take(urls))
    .catch(() => {});
  onOpenUrl(take).catch(() => {});
}
