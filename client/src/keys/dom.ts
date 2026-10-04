// What the keyboard layer knows about the page. It goes by class names rather than by props threaded through every
// component, so a new kind of block or button is reachable without touching this module

export type Pane = "thread" | "chats";

export const SELECTORS = {
  thread: ".thread",
  chatList: ".sidebar .chat-list",
  chatItem: ".chat-list .chat-open",
  activeChat: ".chat-row.active .chat-open",
  composer: ".composer textarea",
  dock: ".dock",
  turn: ".thread-content > .turn",
  settingsButton: ".settings-button",
};

/** Marks the block (or chat) each pane's cursor is on; the cursor's highlight is drawn from it in keys.css */
export const CURSOR = "data-vim-cursor";

/** The keyboard layer's own elements, which it leaves out of hints, searches and focus tracking */
export const VIM_UI = "[data-vim-ui]";

/**
 * What j and k step through in the thread, in document order. A match that contains another match gives way to it,
 * so a list steps through its items, a card through its places, and research through its agents' windows
 */
const BLOCKS = [
  ".prompt",
  ".activity",
  ".turn-note",
  ".markdown > :not(hr, ul, ol)",
  ".markdown > ul > li",
  ".markdown > ol > li",
  ".reply > .materialize",
  ".place",
  ".link-row",
  ".video",
  ".spotify-row",
  ".research-header",
  ".crew-toggle",
  ".window",
  ".research-writing",
  ".report-title",
  ".report-section > h2",
  ".report-citations",
  ".report-sources",
  "[data-nav-block]",
].join(", ");

/** Things a click does something on; anything else with a pointer cursor counts too (see `clickables`) */
export const CLICKABLE = [
  "a[href]",
  "button:not(:disabled)",
  "summary",
  "label:has(> input)",
  "input:not([type=hidden]):not(:disabled)",
  "textarea:not(:disabled)",
  "select:not(:disabled)",
  "[contenteditable=true]",
  "[role=button]",
  "[role=link]",
  "[role=option]",
  "[role=tab]",
  "[role=switch]",
  "[role=checkbox]",
  "[role=radio]",
  "[role=menuitem]",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

const FOCUSABLE = "a[href], button, input, select, textarea, summary, [contenteditable=true], [tabindex]";

const TEXT_INPUT = /^(text|search|email|url|tel|password|number|date|time|datetime-local|month|week)$/;

/** Typing goes into it, so the layer stays out of the way (insert mode) */
export function isEditable(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false;
  if (element.isContentEditable) return true;
  if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return true;
  return element instanceof HTMLInputElement && TEXT_INPUT.test(element.type);
}

export const isVimUi = (element: Element | null) => !!element?.closest(VIM_UI);

/** The app's open modal dialog (e.g. settings); the keyboard layer's own help sheet doesn't count */
/** The topmost open dialog: one opened from another (the prompt editor over the settings) comes later in the page */
export function openDialog(): HTMLDialogElement | null {
  const open = document.querySelectorAll<HTMLDialogElement>(`dialog[open]:not(${VIM_UI})`);
  return open[open.length - 1] ?? null;
}

export function paneOf(element: Element | null): Pane | null {
  if (!element) return null;
  if (element.closest(".sidebar")) return "chats";
  if (element.closest(SELECTORS.thread)) return "thread";
  return null;
}

export const paneRoot = (pane: Pane) =>
  document.querySelector<HTMLElement>(pane === "chats" ? SELECTORS.chatList : SELECTORS.thread);

export const composer = () => document.querySelector<HTMLTextAreaElement>(SELECTORS.composer);

const isRendered = (element: Element) => element.getClientRects().length > 0;

/** The pane's stops in order: blocks of the thread, or chats in the list */
export function items(pane: Pane): HTMLElement[] {
  if (pane === "chats") return [...document.querySelectorAll<HTMLElement>(SELECTORS.chatItem)].filter(isRendered);
  const all = [...document.querySelectorAll<HTMLElement>(`${SELECTORS.thread} :is(${BLOCKS})`)];
  // In document order a container comes right before the first match inside it, so one look ahead is enough
  return all.filter((element, index) => !all[index + 1] || !element.contains(all[index + 1])).filter(isRendered);
}

export const cursorIn = (pane: Pane) => paneRoot(pane)?.querySelector<HTMLElement>(`[${CURSOR}]`) ?? null;

/** The block a node is in, or the last block before it when it sits between blocks */
export function itemContaining(pane: Pane, node: Node): HTMLElement | null {
  const list = items(pane);
  const inside = list.find((item) => item.contains(node));
  if (inside) return inside;
  const before = list.filter((item) => item.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
  return before[before.length - 1] ?? list[0] ?? null;
}

/** The band of the pane where content can be read: under the window's drag strip and above the floating input */
export function viewport(pane: Pane): { top: number; bottom: number } {
  const root = paneRoot(pane);
  const rect = root?.getBoundingClientRect() ?? { top: 0, bottom: window.innerHeight };
  if (pane === "chats") return { top: rect.top, bottom: rect.bottom };
  const dock = document.querySelector(SELECTORS.dock)?.getBoundingClientRect();
  // The thread fades out under the top edge, so text there counts as out of view
  return { top: rect.top + 56, bottom: Math.min(rect.bottom, dock?.top ?? rect.bottom) - 8 };
}

export function isInView(element: Element, pane: Pane): boolean {
  const rect = element.getBoundingClientRect();
  const view = viewport(pane);
  return rect.bottom > view.top && rect.top < view.bottom;
}

/** Index of the first stop at least partly in view, or 0 */
export function firstInView(list: HTMLElement[], pane: Pane): number {
  const index = list.findIndex((item) => isInView(item, pane));
  return index < 0 ? 0 : index;
}

/** Index of the last stop at least partly in view, or the last one */
export function lastInView(list: HTMLElement[], pane: Pane): number {
  for (let index = list.length - 1; index >= 0; index--) if (isInView(list[index], pane)) return index;
  return list.length - 1;
}

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const scrollBehavior = (instant = false): ScrollBehavior => (instant || prefersReducedMotion() ? "auto" : "smooth");

export type Placement = "nearest" | "center" | "start" | "end";

/** Scrolls the pane so `rect` sits where asked within the readable band */
export function revealRect(rect: { top: number; bottom: number }, pane: Pane, placement: Placement, instant = false) {
  const root = paneRoot(pane);
  if (!root) return;
  const view = viewport(pane);
  const height = rect.bottom - rect.top;
  let delta = 0;
  if (placement === "center") delta = rect.top + height / 2 - (view.top + view.bottom) / 2;
  else if (placement === "start") delta = rect.top - view.top;
  else if (placement === "end") delta = rect.bottom - view.bottom;
  else if (rect.top < view.top) delta = rect.top - view.top;
  // Something taller than the band lines up with its top, so its start is never scrolled past
  else if (rect.bottom > view.bottom) delta = Math.min(rect.bottom - view.bottom, rect.top - view.top);
  if (Math.abs(delta) >= 1) root.scrollBy({ top: delta, behavior: scrollBehavior(instant) });
}

export const reveal = (element: Element, pane: Pane, placement: Placement = "nearest", instant = false) =>
  revealRect(element.getBoundingClientRect(), pane, placement, instant);

/** Moves the cursor mark onto `element` and focuses it, so Enter, screen readers and the highlight all follow it */
export function markCursor(element: HTMLElement, pane: Pane, focus = true) {
  paneRoot(pane)
    ?.querySelectorAll(`[${CURSOR}]`)
    .forEach((old) => old !== element && old.removeAttribute(CURSOR));
  element.setAttribute(CURSOR, "");
  if (!focus) return;
  if (!element.matches(FOCUSABLE)) element.setAttribute("tabindex", "-1");
  element.focus({ preventScroll: true });
}

/** Focuses the pane itself, for when it has nothing to put the cursor on yet */
export function focusPaneRoot(pane: Pane) {
  const root = paneRoot(pane);
  if (!root) return;
  if (!root.hasAttribute("tabindex")) root.setAttribute("tabindex", "-1");
  root.focus({ preventScroll: true });
}

/** Whether Enter on the focused element should do what Enter natively does there (click a button, follow a link) */
export const handlesEnter = (element: Element | null) =>
  element instanceof HTMLElement &&
  !element.hasAttribute(CURSOR) &&
  element.matches("a[href], button, summary, [role=button], [role=link], input[type=checkbox], input[type=radio]");

/** Controls inside `scope` that can take focus, in tab order, for stepping through a dialog with j and k */
export function focusables(scope: Element): HTMLElement[] {
  return [...scope.querySelectorAll<HTMLElement>(CLICKABLE)].filter(
    (element) => isRendered(element) && !element.closest("[inert]") && !(element instanceof HTMLLabelElement),
  );
}

/**
 * Clickable things inside `scope`, outermost first: anything matching CLICKABLE, plus elements given a pointer cursor
 * (e.g. a clickable header), which is how Vimium finds them too. Words, icons and off-screen turns are skipped
 */
export function clickables(scope: Element): HTMLElement[] {
  const found: HTMLElement[] = [];
  const walk = (parent: Element, parentPointer: boolean) => {
    for (const child of parent.children) {
      if (!(child instanceof HTMLElement)) continue;
      if (child.classList.contains("w") || child.matches(`${VIM_UI}, [inert], [hidden]`)) continue;
      if (child.matches(SELECTORS.turn) && !isOnScreen(child.getBoundingClientRect())) continue;
      const style = getComputedStyle(child);
      if (style.display === "none") continue;
      const pointer = style.cursor === "pointer";
      if (child.matches(CLICKABLE) || (pointer && !parentPointer)) {
        found.push(child);
        continue;
      }
      walk(child, pointer);
    }
  };
  if (scope instanceof HTMLElement && scope.matches(CLICKABLE)) return [scope];
  walk(scope, false);
  return found;
}

const isOnScreen = (rect: DOMRect) =>
  rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;

/** Where a hint for `element` goes, or null when it can't be seen: off screen, transparent, faded out or covered */
export function visibleRect(element: HTMLElement): DOMRect | null {
  const rect = element.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2 || !isOnScreen(rect)) return null;
  const style = getComputedStyle(element);
  if (style.visibility !== "visible" || Number(style.opacity) === 0) return null;
  const pane = paneOf(element);
  if (pane === "thread") {
    const view = viewport("thread");
    const middle = (rect.top + rect.bottom) / 2;
    if (middle < view.top - 24 || middle > view.bottom + 8) return null;
  }
  // Something else may sit on top of it, e.g. the input floating over the thread; test a few points across it
  const clampX = (x: number) => Math.min(Math.max(x, 1), window.innerWidth - 1);
  const clampY = (y: number) => Math.min(Math.max(y, 1), window.innerHeight - 1);
  const points: [number, number][] = [
    [(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2],
    [rect.left + Math.min(6, rect.width / 2), rect.top + Math.min(6, rect.height / 2)],
    [rect.right - Math.min(6, rect.width / 2), rect.bottom - Math.min(6, rect.height / 2)],
  ];
  for (const [x, y] of points) {
    const hit = document.elementFromPoint(clampX(x), clampY(y));
    if (hit && (hit === element || element.contains(hit))) return rect;
  }
  return null;
}

/** Text the user has selected with the mouse, if any (not inside an input) */
export function selectedText(): string {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || isEditable(document.activeElement)) return "";
  return selection.toString();
}
