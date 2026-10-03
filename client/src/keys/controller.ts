// The keyboard layer's brain: reads keys in the capture phase, keeps vim's modes, and runs the bindings in keymap.ts.
// It's plain TypeScript with a subscribe/get store for the bits React draws (status line, hints, command line, help)

import { getCurrentWindow } from "@tauri-apps/api/window";
import type { ChatSummary, Turn } from "../agent";
import { copyText } from "../chat/clipboard";
import type { Setting } from "../settings/schema";
import { settings } from "../settings/store";
import * as dom from "./dom";
import { complete, runEx, type ExApi } from "./ex";
import { displayKeys, keyToken, lookup, type Action, type Binding } from "./keymap";
import { clearHighlight, findAll, highlight, nextMatch } from "./search";

/** What the app hands the keyboard layer; read fresh on every key, so it's never stale */
export type AppApi = {
  chats: ChatSummary[];
  activeId: string;
  turns: Turn[];
  /** The chat on screen has a reply coming in */
  busy: boolean;
  /** Chats with a reply coming in */
  answering: Set<string>;
  sidebarOpen: boolean;
  toggleSidebar(): void;
  openChat(id: string): void;
  newChat(): void;
  deleteChat(id: string): void;
  stop(): void;
  restart(): void;
};

/** `hidden` once what it points at has scrolled out of sight; the label stays taken so the others don't shift */
export type Hint = { label: string; left: number; top: number; hidden?: boolean };

export type LineKind = ":" | "/";

export type KeyboardState = {
  /** Insert while typing into a field, normal otherwise */
  mode: "normal" | "insert";
  pane: dom.Pane | "composer" | "dialog";
  /** Where the cursor is in its pane, e.g. "4/37" */
  position?: string;
  /** Count and keys typed so far, e.g. "2g" */
  pending: string;
  /** Shown when a key sequence is half typed: what can follow */
  whichKey: { typed: number; bindings: Binding[] } | null;
  message?: { text: string; error?: boolean };
  /** A yes/no question, answered with y */
  confirm?: string;
  hints: { items: Hint[]; typed: string } | null;
  line: LineKind | null;
  help: boolean;
};

// Home row first, so most hints are one easy key
const HINT_KEYS = "fjdkslaghrueiwo";

/**
 * Labels for `count` hints, as short as possible and none the start of another, so typing one never waits for more.
 * Built breadth-first over strings, as Vimium does
 */
function hintLabels(count: number): string[] {
  const labels = [""];
  let offset = 0;
  while (labels.length - offset < count || labels.length === 1) {
    const prefix = labels[offset++];
    for (const key of HINT_KEYS) labels.push(prefix + key);
  }
  return labels.slice(offset, offset + count);
}

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);

const isMac = /Mac|iPhone|iPad/.test(navigator.userAgent);

/** Runs after React has committed and run effects for what the current key changed (e.g. the input's autofocus) */
const later = (run: () => void) => window.setTimeout(run, 0);

const shorten = (text: string, length = 40) => {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > length ? `${line.slice(0, length - 1)}…` : line;
};

export function createKeyboard(app: () => AppApi) {
  let state: KeyboardState = { mode: "insert", pane: "composer", pending: "", whichKey: null, hints: null, line: null, help: false };
  const listeners = new Set<() => void>();
  const update = (patch: Partial<KeyboardState>) => {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  };

  let keys: string[] = [];
  let count = "";
  let lastPane: dom.Pane = "thread";
  /** What y copied, for p; also on the system clipboard */
  let register = "";
  let onYes: (() => void) | null = null;
  let hintTargets: HTMLElement[] = [];
  let search: { query: string; last: Range | null } | null = null;
  /** Where the line was opened from; `from` is where a search starts, fixed before closing the line moves the cursor */
  let lineOrigin: { pane: dom.Pane; scrollTop: number; from: Range } | null = null;
  const history: Record<LineKind, string[]> = { ":": [], "/": [] };
  const chat = { current: "", previous: "" };
  let helpG = false;
  let whichKeyTimer = 0;
  let messageTimer = 0;

  function message(text: string, error = false) {
    window.clearTimeout(messageTimer);
    update({ message: { text, error } });
    messageTimer = window.setTimeout(() => update({ message: undefined }), error ? 6000 : 3500);
  }

  function ask(question: string, yes: () => void) {
    onYes = yes;
    update({ confirm: `${question} (y/n)` });
  }

  function consume(event: KeyboardEvent) {
    event.preventDefault();
    event.stopPropagation();
  }

  function reset() {
    keys = [];
    count = "";
    window.clearTimeout(whichKeyTimer);
    if (state.pending || state.whichKey) update({ pending: "", whichKey: null });
  }

  function showPending() {
    update({ pending: count + displayKeys(keys.join("")), whichKey: null });
    window.clearTimeout(whichKeyTimer);
    if (!keys.length) return;
    const typed = [...keys];
    whichKeyTimer = window.setTimeout(() => {
      const bindings = lookup(lastPane, typed).continuations.filter((binding) => !binding.hidden);
      update({ whichKey: { typed: typed.length, bindings } });
    }, 250);
  }

  // ---- Modes and panes ----

  function positionOf(pane: dom.Pane): string | undefined {
    const list = dom.items(pane);
    if (!list.length) return undefined;
    const cursor = dom.cursorIn(pane);
    const index = cursor ? list.indexOf(cursor) : -1;
    return `${index < 0 ? "–" : index + 1}/${list.length}`;
  }

  /** Mode and pane follow focus, so clicks, Tab and the app's own focus changes all keep them right */
  function syncMode() {
    const active = document.activeElement;
    if (dom.isVimUi(active)) return;
    const insert = dom.isEditable(active);
    const pane = dom.openDialog()
      ? "dialog"
      : insert && active?.closest(dom.SELECTORS.dock)
        ? "composer"
        : (dom.paneOf(active) ?? lastPane);
    if (pane === "thread" || pane === "chats") lastPane = pane;
    // A chat reached with Tab or a click becomes the list's cursor
    if (active instanceof HTMLElement && active.matches(dom.SELECTORS.chatItem)) dom.markCursor(active, "chats", false);
    const mode = insert ? "insert" : "normal";
    const position = !insert && (pane === "thread" || pane === "chats") ? positionOf(pane) : undefined;
    if (mode === state.mode && pane === state.pane && position === state.position) return;
    update({ mode, pane, position });
  }

  const onFocusChange = () => queueMicrotask(syncMode);

  function setCursor(element: HTMLElement, pane: dom.Pane, placement: dom.Placement | null = "nearest", instant = false) {
    dom.markCursor(element, pane);
    lastPane = pane;
    if (placement) dom.reveal(element, pane, placement, instant);
    update({ position: positionOf(pane) });
  }

  /**
   * The thread's cursor, unless it has been scrolled out of view: then j and k start over from what's on screen, the
   * way vim's cursor moves along when the view scrolls. The chat list keeps its cursor wherever it is
   */
  function liveCursor(pane: dom.Pane): HTMLElement | null {
    const cursor = dom.cursorIn(pane);
    if (!cursor || pane === "chats") return cursor;
    return dom.isInView(cursor, pane) ? cursor : null;
  }

  function focusPane(pane: dom.Pane, opened = false) {
    if (pane === "chats" && !app().sidebarOpen) {
      if (opened) return;
      app().toggleSidebar();
      // The list can't take focus until it's drawn open
      later(() => focusPane("chats", true));
      return;
    }
    const list = dom.items(pane);
    const cursor = liveCursor(pane);
    const fallback =
      pane === "chats"
        ? (document.querySelector<HTMLElement>(dom.SELECTORS.activeChat) ?? list[0])
        : list[dom.lastInView(list, pane)];
    const target = cursor && list.includes(cursor) ? cursor : fallback;
    if (target) return setCursor(target, pane);
    dom.focusPaneRoot(pane);
    lastPane = pane;
  }

  function focusComposer(where?: "start" | "end") {
    const box = dom.composer();
    if (!box) return;
    box.focus();
    if (where) {
      const at = where === "start" ? 0 : box.value.length;
      box.setSelectionRange(at, at);
    }
  }

  function leaveInsert(active: Element) {
    const pane = dom.paneOf(active) ?? "thread";
    (active as HTMLElement).blur();
    focusPane(pane);
    if (app().busy) message("Esc again stops the reply");
  }

  // ---- Moving around ----

  function step(pane: dom.Pane, delta: 1 | -1, times: number, instant: boolean) {
    const list = dom.items(pane);
    if (!list.length) return message(pane === "chats" ? "No chats yet" : "Nothing here yet");
    const cursor = liveCursor(pane);
    let index = cursor ? list.indexOf(cursor) : -1;
    if (index < 0 && pane === "chats") {
      const active = document.querySelector<HTMLElement>(dom.SELECTORS.activeChat);
      index = active ? list.indexOf(active) : -1;
    }
    // With no cursor yet, the first step lands on the first (or last) block on screen
    if (index < 0) index = delta > 0 ? dom.firstInView(list, pane) - 1 : dom.lastInView(list, pane) + 1;
    setCursor(list[clamp(index + delta * times, 0, list.length - 1)], pane, "nearest", instant);
  }

  function edge(pane: dom.Pane, end: boolean) {
    const list = dom.items(pane);
    if (!list.length) return;
    const toBottom = end && pane === "thread";
    setCursor(end ? list[list.length - 1] : list[0], pane, toBottom ? null : end ? "end" : "start");
    // At the end of the thread, go all the way down so new text is followed again
    if (toBottom) dom.paneRoot(pane)?.scrollTo({ top: 1e9, behavior: dom.scrollBehavior() });
  }

  const prompts = () => dom.items("thread").filter((item) => item.matches(".prompt"));

  function gotoMessage(n: number) {
    const list = prompts();
    if (!list.length) return message("No messages yet");
    setCursor(list[clamp(n - 1, 0, list.length - 1)], "thread", "start");
  }

  /** } and {: the next message, or back to the start of this one */
  function jumpMessage(delta: 1 | -1, times: number) {
    const list = dom.items("thread");
    if (!list.length) return;
    const cursor = liveCursor("thread");
    const index = cursor ? list.indexOf(cursor) : delta > 0 ? dom.firstInView(list, "thread") - 1 : dom.lastInView(list, "thread") + 1;
    const starts = list.map((item, at) => (item.matches(".prompt") ? at : -1)).filter((at) => at >= 0);
    const ahead = delta > 0 ? starts.filter((at) => at > index) : starts.filter((at) => at < index).reverse();
    const target = ahead[Math.min(times, ahead.length) - 1] ?? (delta > 0 ? list.length - 1 : 0);
    setCursor(list[target], "thread", list[target].matches(".prompt") ? "start" : "nearest");
  }

  function screen(where: "top" | "middle" | "bottom") {
    const list = dom.items("thread");
    const view = dom.viewport("thread");
    const whole = list.filter((item) => {
      const rect = item.getBoundingClientRect();
      return rect.top >= view.top - 1 && rect.bottom <= view.bottom + 1;
    });
    const pool = whole.length ? whole : list.filter((item) => dom.isInView(item, "thread"));
    if (!pool.length) return;
    let target = where === "top" ? pool[0] : pool[pool.length - 1];
    if (where === "middle") {
      const middle = (view.top + view.bottom) / 2;
      const distance = (item: HTMLElement) => {
        const rect = item.getBoundingClientRect();
        return Math.abs((rect.top + rect.bottom) / 2 - middle);
      };
      target = pool.reduce((best, item) => (distance(item) < distance(best) ? item : best));
    }
    setCursor(target, "thread", null);
  }

  /** Ctrl-d, Ctrl-u, Ctrl-f, Ctrl-b: scrolls by part of a screen and keeps the cursor at the same height on screen */
  function page(fraction: number, times: number, instant: boolean) {
    const root = dom.paneRoot("thread");
    if (!root) return;
    const view = dom.viewport("thread");
    const target = clamp(root.scrollTop + (view.bottom - view.top) * fraction * times, 0, root.scrollHeight - root.clientHeight);
    const shift = target - root.scrollTop;
    const list = dom.items("thread");
    let pick: HTMLElement | undefined;
    if (Math.abs(shift) < 1) {
      // Already at the end, so the cursor goes there, as in vim
      pick = fraction > 0 ? list[list.length - 1] : list[0];
    } else {
      const anchor = liveCursor("thread")?.getBoundingClientRect().top ?? view.top;
      let best = Infinity;
      for (const item of list) {
        const rect = item.getBoundingClientRect();
        const top = rect.top - shift;
        if (top >= view.bottom || rect.bottom - shift <= view.top) continue;
        if (Math.abs(top - anchor) < best) {
          best = Math.abs(top - anchor);
          pick = item;
        }
      }
    }
    root.scrollTo({ top: target, behavior: dom.scrollBehavior(instant) });
    if (pick) setCursor(pick, "thread", null);
  }

  function scrollLines(delta: number, instant: boolean) {
    dom.paneRoot("thread")?.scrollBy({ top: delta * 48, behavior: dom.scrollBehavior(instant) });
  }

  function place(placement: dom.Placement) {
    const cursor = dom.cursorIn("thread");
    if (cursor) dom.reveal(cursor, "thread", placement);
  }

  // ---- Doing things ----

  /** Clicks `target` as a mouse would. In the thread the cursor moves to its block rather than focus leaving it */
  function activate(target: HTMLElement) {
    if (dom.isEditable(target)) return target.focus();
    const block = dom.paneOf(target) === "thread" ? dom.itemContaining("thread", target) : null;
    if (block) setCursor(block, "thread", null);
    else if (target.matches("a[href], button, input, select, summary, [tabindex]")) target.focus({ preventScroll: true });
    target.click();
    // What opened may grow, and the thread pins its bottom while following new text; keep the block in view
    if (block) later(() => requestAnimationFrame(() => block.isConnected && dom.reveal(block, "thread")));
  }

  /** Enter on a block: clicks the one thing in it, or labels them when there are several */
  function openBlock() {
    const block = liveCursor("thread");
    if (!block) return step("thread", 1, 1, false);
    if (block.matches(dom.CLICKABLE)) return activate(block);
    const targets = dom.clickables(block).filter((target) => dom.visibleRect(target));
    if (!targets.length) return message("Nothing to open here");
    if (targets.length === 1) return activate(targets[0]);
    startHints(block);
  }

  function startHints(scope?: Element) {
    const root = scope ?? dom.openDialog() ?? document.body;
    const found = dom
      .clickables(root)
      .map((element) => ({ element, rect: dom.visibleRect(element) }))
      .filter((entry): entry is { element: HTMLElement; rect: DOMRect } => entry.rect !== null);
    if (!found.length) return message("Nothing to click here", true);
    // Reading order, so labels run top to bottom and left to right
    found.sort((a, b) => (Math.abs(a.rect.top - b.rect.top) > 6 ? a.rect.top - b.rect.top : a.rect.left - b.rect.left));
    const labels = hintLabels(found.length);
    hintTargets = found.map((entry) => entry.element);
    const items = found.map((entry, index) => ({ label: labels[index], left: entry.rect.left, top: entry.rect.top }));
    update({ hints: { items, typed: "" } });
    // The thread keeps scrolling while a reply streams in, so labels follow what they point at rather than closing
    window.addEventListener("scroll", moveHints, { capture: true, passive: true });
    window.addEventListener("resize", moveHints);
  }

  let hintFrame = 0;

  function moveHints() {
    if (hintFrame) return;
    hintFrame = requestAnimationFrame(() => {
      hintFrame = 0;
      if (!state.hints) return;
      const items = state.hints.items.map((hint, index) => {
        const rect = hintTargets[index].isConnected ? dom.visibleRect(hintTargets[index]) : null;
        return rect ? { ...hint, left: rect.left, top: rect.top, hidden: false } : { ...hint, hidden: true };
      });
      update({ hints: { ...state.hints, items } });
    });
  }

  function endHints() {
    window.removeEventListener("scroll", moveHints, { capture: true });
    window.removeEventListener("resize", moveHints);
    cancelAnimationFrame(hintFrame);
    hintFrame = 0;
    hintTargets = [];
    if (state.hints) update({ hints: null });
  }

  function hintKey(token: string) {
    const hints = state.hints!;
    if (token === "<Esc>" || token === "<C-c>") return endHints();
    if (token === "<BS>") return update({ hints: { ...hints, typed: hints.typed.slice(0, -1) } });
    if (!/^[a-z]$/i.test(token)) return;
    const typed = hints.typed + token.toLowerCase();
    if (!hints.items.some((hint) => hint.label.startsWith(typed))) return;
    const index = hints.items.findIndex((hint) => hint.label === typed);
    if (index < 0) return update({ hints: { ...hints, typed } });
    const target = hintTargets[index];
    endHints();
    if (target.isConnected) activate(target);
    else message("That's gone now", true);
  }

  function turnOf(element: Element): Turn | undefined {
    const section = element.closest(dom.SELECTORS.turn);
    if (!section) return undefined;
    return app().turns[[...document.querySelectorAll(dom.SELECTORS.turn)].indexOf(section)];
  }

  async function yank(text: string, flash?: Element | null) {
    register = text;
    // A brief glow on what was copied, like highlight-on-yank; the Web Animations API leaves CSS animations alone
    flash?.animate([{ backgroundColor: "color-mix(in srgb, currentColor 16%, transparent)" }], { duration: 650, easing: "ease-out" });
    const lines = text.split("\n").length;
    try {
      await copyText(text);
      message(lines > 1 ? `${lines} lines copied` : `Copied “${shorten(text)}”`);
    } catch {
      message("Kept for p (the system clipboard wasn't available)");
    }
  }

  function yankBlock() {
    const block = liveCursor("thread");
    if (!block) return message("Move to a block first (j, k)", true);
    const turn = block.matches(".prompt") ? turnOf(block) : undefined;
    // A code block copies its code alone, as its copy button does (chat/CodeBlock.tsx)
    const code = block.matches("pre, .code-block") ? block.querySelector("code") ?? block : null;
    const text = turn
      ? `${turn.command ? `/${turn.command} ` : ""}${turn.prompt}`
      : code
        ? (code.textContent ?? "").replace(/\n$/, "")
        : block.innerText.trim();
    yank(text, block);
  }

  function yankReply() {
    const block = liveCursor("thread");
    const reply = block?.closest(dom.SELECTORS.turn)?.querySelector<HTMLElement>(".reply");
    if (!block || !reply) return message("Move to a message first (j, k)", true);
    const markdown = turnOf(block)
      ?.parts.flatMap((part) => (part.kind === "text" ? [part.text] : []))
      .join("\n\n")
      .trim();
    const text = markdown || reply.innerText.trim();
    if (!text) return message("No reply to copy yet", true);
    yank(text, reply);
  }

  function put(before: boolean) {
    if (!register) return message("Nothing copied yet (yy copies a block)", true);
    const box = dom.composer();
    if (!box) return;
    box.focus();
    const at = before ? 0 : box.value.length;
    box.setSelectionRange(at, at);
    // insertText goes through React's onChange like typing, and can be undone
    if (!document.execCommand("insertText", false, register)) {
      const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setValue?.call(box, box.value.slice(0, at) + register + box.value.slice(at));
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  // ---- Chats ----

  /** The chat a list row is for; the list draws chats in order, and the title guards against it ever not */
  function chatOf(item: Element | null): ChatSummary | undefined {
    if (!item) return undefined;
    const { chats } = app();
    const title = item.getAttribute("title");
    const byIndex = chats[dom.items("chats").indexOf(item as HTMLElement)];
    if (byIndex && (title === null || byIndex.title === title)) return byIndex;
    return chats.find((candidate) => candidate.title === title);
  }

  function focusActiveChat() {
    const active = document.querySelector<HTMLElement>(dom.SELECTORS.activeChat);
    if (active) setCursor(active, "chats");
    else focusPane("chats");
  }

  /** Opens a chat but stays in normal mode: the app focuses the input on a chat switch, so focus comes back after */
  function switchChat(id: string, after: dom.Pane) {
    app().openChat(id);
    later(() => (after === "chats" && app().sidebarOpen ? focusActiveChat() : focusPane("thread")));
  }

  function openChatAtCursor() {
    const chatHere = chatOf(dom.cursorIn("chats"));
    if (!chatHere) return;
    if (chatHere.id !== app().activeId) return switchChat(chatHere.id, "thread");
    focusPane("thread");
  }

  function deleteChatAtCursor() {
    const item = dom.cursorIn("chats");
    const target = chatOf(item);
    if (!item || !target) return;
    const index = dom.items("chats").indexOf(item);
    ask(`Delete “${shorten(target.title, 32)}” and what the agent remembers from it?`, () => {
      app().deleteChat(target.id);
      later(() => {
        const list = dom.items("chats");
        if (list.length) setCursor(list[Math.min(index, list.length - 1)], "chats");
        else focusPane("thread");
      });
    });
  }

  function deleteCurrentChat(force: boolean) {
    const { chats, activeId } = app();
    const current = chats.find((candidate) => candidate.id === activeId);
    if (!current) return message("This chat has nothing to delete yet");
    const remove = () => app().deleteChat(current.id);
    if (force) return remove();
    ask(`Delete “${shorten(current.title, 32)}” and what the agent remembers from it?`, remove);
  }

  function cycleChat(direction: 1 | -1, times = 1) {
    const { chats, activeId } = app();
    if (!chats.length) return message("No chats yet", true);
    const index = chats.findIndex((candidate) => candidate.id === activeId);
    // A new chat isn't in the list yet, so gt starts at the top and gT at the bottom
    const from = index < 0 ? (direction > 0 ? -1 : chats.length) : index;
    const next = chats[(((from + direction * times) % chats.length) + chats.length) % chats.length];
    if (next.id !== activeId) switchChat(next.id, lastPane);
  }

  function gotoChat(n: number) {
    const target = app().chats[n - 1];
    if (!target) return message(`E86: Chat ${n} doesn't exist`, true);
    if (target.id !== app().activeId) switchChat(target.id, lastPane);
  }

  function altChat() {
    const previous = chat.previous;
    if (!previous || !app().chats.some((candidate) => candidate.id === previous)) return message("E23: No alternate chat", true);
    switchChat(previous, lastPane);
  }

  function toggleChats() {
    const wasOpen = app().sidebarOpen;
    app().toggleSidebar();
    if (!wasOpen) later(() => focusPane("chats", true));
    else if (lastPane === "chats") focusPane("thread");
  }

  function hideChats() {
    if (app().sidebarOpen) app().toggleSidebar();
    focusPane("thread");
  }

  // ---- App ----

  function stop() {
    if (!app().busy) return message("Nothing to stop");
    app().stop();
  }

  function cycleTheme() {
    const theme = (settings.definitions as Record<string, Setting>).theme;
    if (theme?.kind !== "choice") return message("There's no theme setting", true);
    const current = settings.get()["theme" as never];
    const next = theme.options[(theme.options.findIndex((option) => option.value === current) + 1) % theme.options.length];
    settings.set("theme" as never, next.value as never);
    message(`Theme: ${next.label}`);
  }

  function openSettings() {
    const button = document.querySelector<HTMLElement>(dom.SELECTORS.settingsButton);
    if (!button) return message("There are no settings yet", true);
    button.click();
  }

  async function quit(force: boolean) {
    if (!force && app().answering.size) return message("E37: A reply is still coming in (add ! to quit anyway)", true);
    try {
      await getCurrentWindow().close();
    } catch {
      message("Couldn't close the window", true);
    }
  }

  // ---- Search ----

  /** Where a search starts from: the cursor's block, or the first one on screen */
  function searchStart(pane: dom.Pane): Range {
    const range = document.createRange();
    const list = dom.items(pane);
    const anchor = liveCursor(pane) ?? list[pane === "chats" ? 0 : dom.firstInView(list, pane)] ?? dom.paneRoot(pane);
    if (anchor) {
      range.selectNodeContents(anchor);
      range.collapse(true);
    }
    return range;
  }

  function showMatch(pane: dom.Pane, matches: Range[], index: number, wrapped: boolean, backwards: boolean) {
    const match = matches[index];
    if (search) search.last = match;
    highlight(matches, match);
    const block = dom.itemContaining(pane, match.startContainer);
    if (block) setCursor(block, pane, null);
    dom.revealRect(match.getBoundingClientRect(), pane, "nearest");
    const wrap = wrapped ? (backwards ? "Search hit TOP, continuing at BOTTOM  " : "Search hit BOTTOM, continuing at TOP  ") : "";
    message(`${wrap}[${index + 1}/${matches.length}]`);
  }

  /** As the search is typed: highlights the matches and scrolls to the next one, without moving the cursor yet */
  function previewSearch(query: string): number {
    if (!lineOrigin) return 0;
    const { pane, scrollTop, from } = lineOrigin;
    const root = dom.paneRoot(pane);
    const matches = root ? findAll(root, query) : [];
    if (!matches.length) {
      clearHighlight();
      if (root) root.scrollTop = scrollTop;
      return 0;
    }
    const { index } = nextMatch(matches, from, false);
    highlight(matches, matches[index]);
    dom.revealRect(matches[index].getBoundingClientRect(), pane, "nearest", true);
    return matches.length;
  }

  function commitSearch(query: string, origin: NonNullable<typeof lineOrigin>) {
    // An empty search repeats the last one, as in vim
    const pattern = query || search?.query;
    if (!pattern) return clearHighlight();
    search = { query: pattern, last: null };
    const root = dom.paneRoot(origin.pane);
    const matches = root ? findAll(root, pattern) : [];
    if (!matches.length) {
      clearHighlight();
      if (root) root.scrollTop = origin.scrollTop;
      return message(`E486: Pattern not found: ${pattern}`, true);
    }
    const { index, wrapped } = nextMatch(matches, origin.from, false);
    showMatch(origin.pane, matches, index, wrapped, false);
  }

  function searchAgain(backwards: boolean, times: number) {
    if (!search) return message("E35: No previous search", true);
    const pane = lastPane;
    const root = dom.paneRoot(pane);
    const matches = root ? findAll(root, search.query) : [];
    if (!root || !matches.length) return message(`E486: Pattern not found: ${search.query}`, true);
    // Carry on from the last match while the cursor is still on it; after moving away, from the cursor
    const last = search.last;
    const cursor = liveCursor(pane);
    let from = last && last.startContainer.isConnected && cursor?.contains(last.startContainer) ? last : searchStart(pane);
    let index = 0;
    let wrapped = false;
    for (let n = 0; n < times; n++) {
      const next = nextMatch(matches, from, backwards);
      index = next.index;
      wrapped ||= next.wrapped;
      from = matches[index];
    }
    showMatch(pane, matches, index, wrapped, backwards);
  }

  // ---- Command line ----

  function openLine(kind: LineKind) {
    lineOrigin = { pane: lastPane, scrollTop: dom.paneRoot(lastPane)?.scrollTop ?? 0, from: searchStart(lastPane) };
    update({ line: kind });
  }

  /** Closes the line and puts focus back where it was, before anything the line asked for runs */
  function closeLine() {
    const origin = lineOrigin;
    lineOrigin = null;
    update({ line: null });
    if (origin) focusPane(origin.pane);
    return origin;
  }

  function submitLine(kind: LineKind, value: string) {
    if (value.trim()) history[kind] = [...history[kind].filter((entry) => entry !== value), value].slice(-50);
    const origin = closeLine();
    if (kind === ":") runEx(ex, value);
    else if (origin) commitSearch(value, origin);
  }

  function cancelLine(kind: LineKind) {
    // Submitting moves focus away, which blurs the input and lands here after the line has already closed
    const origin = lineOrigin;
    if (!origin) return;
    if (kind === "/") {
      clearHighlight();
      const root = dom.paneRoot(origin.pane);
      if (root) root.scrollTop = origin.scrollTop;
    }
    closeLine();
  }

  const ex: ExApi = {
    chats: () => app().chats,
    openChat: (id) => (id === app().activeId ? undefined : switchChat(id, "thread")),
    altChat,
    cycleChat: (direction) => cycleChat(direction),
    newChat: () => app().newChat(),
    deleteCurrentChat,
    showChats: () => focusPane("chats"),
    stop,
    restart: () => {
      app().restart();
      message("Restarting the agent");
    },
    quit,
    openSettings,
    clearSearch: () => {
      search = search && { ...search, last: null };
      clearHighlight();
    },
    help: () => update({ help: true }),
    gotoMessage,
    message,
  };

  // ---- Keys ----

  function run(action: Action, explicitCount: number | null, event: KeyboardEvent) {
    const times = explicitCount ?? 1;
    const instant = event.repeat;
    const pane = lastPane;
    switch (action) {
      case "down":
        return step(pane, 1, times, instant);
      case "up":
        return step(pane, -1, times, instant);
      case "first":
        return edge(pane, false);
      case "last":
        return explicitCount !== null && pane === "thread" ? gotoMessage(explicitCount) : edge(pane, true);
      case "nextMessage":
        return jumpMessage(1, times);
      case "prevMessage":
        return jumpMessage(-1, times);
      case "screenTop":
        return screen("top");
      case "screenMiddle":
        return screen("middle");
      case "screenBottom":
        return screen("bottom");
      case "halfDown":
        return page(0.5, times, instant);
      case "halfUp":
        return page(-0.5, times, instant);
      case "pageDown":
        return page(0.9, times, instant);
      case "pageUp":
        return page(-0.9, times, instant);
      case "lineDown":
        return scrollLines(times, instant);
      case "lineUp":
        return scrollLines(-times, instant);
      case "center":
        return place("center");
      case "toTop":
        return place("start");
      case "toBottom":
        return place("end");
      case "open":
        return openBlock();
      case "yankBlock":
        return yankBlock();
      case "yankReply":
        return yankReply();
      case "openChat":
        return openChatAtCursor();
      case "deleteChat":
        return deleteChatAtCursor();
      case "hideChats":
        return hideChats();
      case "insert":
        return focusComposer();
      case "insertStart":
        return focusComposer("start");
      case "insertEnd":
        return focusComposer("end");
      case "putAfter":
        return put(false);
      case "putBefore":
        return put(true);
      case "hints":
        return startHints();
      case "search":
        return openLine("/");
      case "searchNext":
        return searchAgain(false, times);
      case "searchPrev":
        return searchAgain(true, times);
      case "commandLine":
        return openLine(":");
      case "help":
        return update({ help: true });
      case "nextChat":
        return explicitCount !== null ? gotoChat(explicitCount) : cycleChat(1);
      case "prevChat":
        return cycleChat(-1, times);
      case "altChat":
        return altChat();
      case "focusChats":
        return focusPane("chats");
      case "focusThread":
        return focusPane("thread");
      case "focusComposer":
        return focusComposer();
      case "cyclePane":
        return pane === "chats" ? focusPane("thread") : focusComposer();
      case "stop":
        return stop();
      case "newChat":
        return app().newChat();
      case "toggleChats":
        return toggleChats();
      case "cycleTheme":
        return cycleTheme();
      case "settings":
        return openSettings();
      case "restart":
        return ex.restart();
      case "deleteCurrentChat":
        return deleteCurrentChat(false);
      case "dialogNext":
      case "dialogPrev":
      case "dialogActivate":
      case "dialogClose":
        return dialogAction(action);
    }
  }

  function dialogAction(action: Action) {
    const dialog = dom.openDialog();
    if (!dialog) return;
    const active = document.activeElement as HTMLElement | null;
    if (action === "dialogClose") return dialog.close();
    if (action === "hints") return startHints(dialog);
    if (action === "dialogActivate") {
      if (active && dialog.contains(active) && active !== dialog) active.click();
      return;
    }
    const controls = dom.focusables(dialog);
    if (!controls.length) return;
    const index = active ? controls.indexOf(active) : -1;
    const delta = action === "dialogNext" ? 1 : -1;
    const next = index < 0 ? (delta > 0 ? 0 : controls.length - 1) : (index + delta + controls.length) % controls.length;
    controls[next].focus();
  }

  function answer(token: string) {
    const yes = onYes;
    onYes = null;
    update({ confirm: undefined });
    if (token === "y" || token === "Y") yes?.();
    else message("Cancelled");
  }

  function helpKey(token: string) {
    const body = document.querySelector<HTMLElement>("[data-vim-help-body]");
    const half = (body?.clientHeight ?? 400) / 2;
    const scroll = (top: number) => body?.scrollBy({ top, behavior: dom.scrollBehavior() });
    const wasG = helpG;
    helpG = false;
    switch (token) {
      case "<Esc>":
      case "<C-c>":
      case "q":
      case "?":
      case "<CR>":
        return update({ help: false });
      case "j":
      case "<Down>":
        return scroll(48);
      case "k":
      case "<Up>":
        return scroll(-48);
      case "<C-d>":
      case "<Space>":
        return scroll(half);
      case "<C-u>":
        return scroll(-half);
      case "G":
        return body?.scrollTo({ top: body.scrollHeight, behavior: dom.scrollBehavior() });
      case "g":
        if (wasG) body?.scrollTo({ top: 0, behavior: dom.scrollBehavior() });
        else helpG = true;
    }
  }

  function dialogKey(event: KeyboardEvent, token: string) {
    // Esc is the dialog's own (it closes), and typing into a field is left alone
    if (token === "<Esc>" || dom.isEditable(document.activeElement)) return;
    const { exact } = lookup("dialog", [token]);
    if (!exact) return;
    consume(event);
    dialogAction(exact.action);
  }

  function insertKey(event: KeyboardEvent, token: string, active: Element) {
    if (token === "<Esc>") {
      consume(event);
      return leaveInsert(active);
    }
    if (token !== "<C-c>") return;
    if (app().busy) {
      consume(event);
      return app().stop();
    }
    // Outside macOS Ctrl-C copies, so with text selected it's left to do that
    const field = active as HTMLTextAreaElement;
    if (!isMac && typeof field.selectionStart === "number" && field.selectionStart !== field.selectionEnd) return;
    consume(event);
    leaveInsert(active);
  }

  function normalKey(event: KeyboardEvent, token: string) {
    if (token === "<Esc>") {
      if (keys.length || count) {
        consume(event);
        return reset();
      }
      clearHighlight();
      update({ message: undefined });
      // Plain Esc goes on to the app, which stops a reply in progress; Ctrl-[ wouldn't, so it stops it here
      if (event.key !== "Escape" && app().busy) {
        consume(event);
        app().stop();
      }
      return;
    }
    if (token === "<C-c>") {
      consume(event);
      reset();
      return stop();
    }
    // Enter on a focused button or link (not the cursor) does what Enter always does there
    if (token === "<CR>" && !keys.length && dom.handlesEnter(document.activeElement)) return;
    // y with text selected copies the selection, like y in visual mode
    if (token === "y" && !keys.length && !count) {
      const selection = dom.selectedText();
      if (selection) {
        consume(event);
        return yank(selection);
      }
    }
    if (/^[0-9]$/.test(token) && !keys.length && (count || token !== "0")) {
      consume(event);
      count += token;
      return showPending();
    }
    const sequence = [...keys, token];
    const { exact, continuations } = lookup(lastPane, sequence);
    if (exact) {
      consume(event);
      const explicitCount = count ? Number(count) : null;
      reset();
      update({ message: undefined });
      return run(exact.action, explicitCount, event);
    }
    if (continuations.length) {
      consume(event);
      keys = sequence;
      return showPending();
    }
    // A half-typed sequence that went nowhere is dropped; an unbound key on its own is left alone
    if (keys.length || count) {
      consume(event);
      reset();
    }
  }

  function onKeyDown(event: KeyboardEvent) {
    if (!event.isTrusted || event.isComposing || event.keyCode === 229 || event.metaKey || event.altKey) return;
    const token = keyToken(event);
    if (!token) return;
    const active = document.activeElement;
    // The command line's input handles its own keys
    if (dom.isVimUi(active) && dom.isEditable(active)) return;
    if (state.confirm) {
      consume(event);
      return answer(token);
    }
    if (state.hints) {
      consume(event);
      return hintKey(token);
    }
    if (dom.openDialog()) return dialogKey(event, token);
    if (state.help) {
      consume(event);
      return helpKey(token);
    }
    if (dom.isEditable(active)) return insertKey(event, token, active!);
    normalKey(event, token);
  }

  /** A click in the thread moves the cursor there, as a click does in vim */
  function onClick(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof Element) || dom.paneOf(target) !== "thread") return;
    if (target.closest(dom.CLICKABLE) || dom.selectedText()) return;
    const block = dom.items("thread").find((item) => item.contains(target));
    if (block) setCursor(block, "thread", null);
  }

  return {
    get: () => state,

    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    /** Starts listening; returns the cleanup */
    attach() {
      window.addEventListener("keydown", onKeyDown, true);
      document.addEventListener("focusin", onFocusChange);
      document.addEventListener("focusout", onFocusChange);
      document.addEventListener("click", onClick);
      syncMode();
      return () => {
        window.removeEventListener("keydown", onKeyDown, true);
        document.removeEventListener("focusin", onFocusChange);
        document.removeEventListener("focusout", onFocusChange);
        document.removeEventListener("click", onClick);
        endHints();
        window.clearTimeout(whichKeyTimer);
        window.clearTimeout(messageTimer);
      };
    },

    /** Called as the chat on screen changes, for Ctrl-^ and :b# */
    chatOpened(id: string) {
      if (id === chat.current) return;
      chat.previous = chat.current;
      chat.current = id;
    },

    submitLine,
    cancelLine,
    previewSearch,
    history: (kind: LineKind) => history[kind],
    completions: (line: string) => complete(line, app().chats),
    closeHelp: () => update({ help: false }),
  };
}

export type Keyboard = ReturnType<typeof createKeyboard>;
