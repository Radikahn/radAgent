// The vim-style key bindings, as data: the keyboard layer runs them, and the help sheet and which-key popup list them

/** Where a binding works: `global` in normal mode anywhere outside a dialog; a pane's own bindings win over global ones */
export type Context = "global" | "thread" | "chats" | "dialog";

export type Action =
  | "down"
  | "up"
  | "first"
  | "last"
  | "nextMessage"
  | "prevMessage"
  | "screenTop"
  | "screenMiddle"
  | "screenBottom"
  | "halfDown"
  | "halfUp"
  | "pageDown"
  | "pageUp"
  | "lineDown"
  | "lineUp"
  | "center"
  | "toTop"
  | "toBottom"
  | "open"
  | "yankBlock"
  | "yankReply"
  | "openChat"
  | "deleteChat"
  | "hideChats"
  | "insert"
  | "insertStart"
  | "insertEnd"
  | "putAfter"
  | "putBefore"
  | "hints"
  | "search"
  | "searchNext"
  | "searchPrev"
  | "commandLine"
  | "help"
  | "nextChat"
  | "prevChat"
  | "altChat"
  | "focusChats"
  | "focusThread"
  | "focusComposer"
  | "cyclePane"
  | "stop"
  | "newChat"
  | "toggleChats"
  | "cycleTheme"
  | "settings"
  | "restart"
  | "deleteCurrentChat"
  | "dialogNext"
  | "dialogPrev"
  | "dialogActivate"
  | "dialogClose";

export type Binding = {
  /** Vim notation: "gg", "<C-d>", "<Space>n" */
  keys: string;
  context: Context;
  action: Action;
  /** What the help sheet and which-key say it does */
  help: string;
  /** The help sheet's heading for it */
  section: string;
  /** Shown in place of `keys` on the help sheet, to list alternatives together */
  label?: string;
  /** Left off the help sheet and which-key (an alternative already listed) */
  hidden?: boolean;
};

const THREAD = "Reading the chat";
const CHATS = "Chat list";
const MOVING = "Chats and panes";
const TYPING = "Writing";
const FINDING = "Finding and running";
const LEADER = "Space menu";
const DIALOG = "In a dialog";

export const BINDINGS: Binding[] = [
  { keys: "j", context: "thread", action: "down", help: "Next block", section: THREAD, label: "j  ↓" },
  { keys: "<Down>", context: "thread", action: "down", help: "Next block", section: THREAD, hidden: true },
  { keys: "k", context: "thread", action: "up", help: "Previous block", section: THREAD, label: "k  ↑" },
  { keys: "<Up>", context: "thread", action: "up", help: "Previous block", section: THREAD, hidden: true },
  { keys: "}", context: "thread", action: "nextMessage", help: "Next message", section: THREAD },
  { keys: "{", context: "thread", action: "prevMessage", help: "Previous message", section: THREAD },
  { keys: "gg", context: "thread", action: "first", help: "First block", section: THREAD },
  { keys: "G", context: "thread", action: "last", help: "Last block; {n}G goes to message n", section: THREAD },
  { keys: "H", context: "thread", action: "screenTop", help: "Top of the screen", section: THREAD },
  { keys: "M", context: "thread", action: "screenMiddle", help: "Middle of the screen", section: THREAD },
  { keys: "L", context: "thread", action: "screenBottom", help: "Bottom of the screen", section: THREAD },
  { keys: "<C-d>", context: "thread", action: "halfDown", help: "Half a screen down", section: THREAD },
  { keys: "<C-u>", context: "thread", action: "halfUp", help: "Half a screen up", section: THREAD },
  { keys: "<C-f>", context: "thread", action: "pageDown", help: "A screen down", section: THREAD },
  { keys: "<C-b>", context: "thread", action: "pageUp", help: "A screen up", section: THREAD },
  { keys: "<C-e>", context: "thread", action: "lineDown", help: "Scroll down a little", section: THREAD },
  { keys: "<C-y>", context: "thread", action: "lineUp", help: "Scroll up a little", section: THREAD },
  { keys: "zz", context: "thread", action: "center", help: "Scroll the block to the middle", section: THREAD },
  { keys: "zt", context: "thread", action: "toTop", help: "Scroll the block to the top", section: THREAD },
  { keys: "zb", context: "thread", action: "toBottom", help: "Scroll the block to the bottom", section: THREAD },
  { keys: "<CR>", context: "thread", action: "open", help: "Open what's in the block (hints when there are several)", section: THREAD, label: "Enter  o" },
  { keys: "o", context: "thread", action: "open", help: "Open what's in the block", section: THREAD, hidden: true },
  { keys: "yy", context: "thread", action: "yankBlock", help: "Copy the block (y alone copies selected text)", section: THREAD },
  { keys: "Y", context: "thread", action: "yankReply", help: "Copy the whole reply as Markdown", section: THREAD },

  { keys: "j", context: "chats", action: "down", help: "Next chat", section: CHATS, label: "j  ↓" },
  { keys: "<Down>", context: "chats", action: "down", help: "Next chat", section: CHATS, hidden: true },
  { keys: "k", context: "chats", action: "up", help: "Previous chat", section: CHATS, label: "k  ↑" },
  { keys: "<Up>", context: "chats", action: "up", help: "Previous chat", section: CHATS, hidden: true },
  { keys: "gg", context: "chats", action: "first", help: "First chat", section: CHATS },
  { keys: "G", context: "chats", action: "last", help: "Last chat", section: CHATS },
  { keys: "<CR>", context: "chats", action: "openChat", help: "Open the chat", section: CHATS, label: "Enter  o  l" },
  { keys: "o", context: "chats", action: "openChat", help: "Open the chat", section: CHATS, hidden: true },
  { keys: "l", context: "chats", action: "openChat", help: "Open the chat", section: CHATS, hidden: true },
  { keys: "dd", context: "chats", action: "deleteChat", help: "Delete the chat (asks first)", section: CHATS },
  { keys: "q", context: "chats", action: "hideChats", help: "Hide the chat list", section: CHATS },

  { keys: "gt", context: "global", action: "nextChat", help: "Next chat; {n}gt opens chat n", section: MOVING },
  { keys: "gT", context: "global", action: "prevChat", help: "Previous chat", section: MOVING },
  { keys: "<C-^>", context: "global", action: "altChat", help: "Back to the chat you were in before", section: MOVING },
  { keys: "<C-h>", context: "global", action: "focusChats", help: "Go to the chat list", section: MOVING, label: "Ctrl-h  Ctrl-w h" },
  { keys: "<C-w>h", context: "global", action: "focusChats", help: "Chat list", section: MOVING, hidden: true },
  { keys: "<C-l>", context: "global", action: "focusThread", help: "Go to the chat", section: MOVING, label: "Ctrl-l  Ctrl-w l" },
  { keys: "<C-w>l", context: "global", action: "focusThread", help: "Chat", section: MOVING, hidden: true },
  { keys: "<C-w>k", context: "global", action: "focusThread", help: "Chat", section: MOVING, hidden: true },
  { keys: "<C-j>", context: "global", action: "focusComposer", help: "Go to the message box", section: MOVING, label: "Ctrl-j  Ctrl-w j" },
  { keys: "<C-w>j", context: "global", action: "focusComposer", help: "Message box", section: MOVING, hidden: true },
  { keys: "<C-w>w", context: "global", action: "cyclePane", help: "Next pane", section: MOVING },

  { keys: "i", context: "global", action: "insert", help: "Write a message", section: TYPING, label: "i  a" },
  { keys: "a", context: "global", action: "insertEnd", help: "Write a message", section: TYPING, hidden: true },
  { keys: "I", context: "global", action: "insertStart", help: "Write, at the start of the message", section: TYPING },
  { keys: "A", context: "global", action: "insertEnd", help: "Write, at the end of the message", section: TYPING },
  { keys: "p", context: "global", action: "putAfter", help: "Put what you copied at the end of the message", section: TYPING },
  { keys: "P", context: "global", action: "putBefore", help: "Put what you copied at the start of the message", section: TYPING },
  { keys: "<C-c>", context: "global", action: "stop", help: "Stop the reply (also works while writing)", section: TYPING },

  { keys: "f", context: "global", action: "hints", help: "Label everything clickable; type a label to click it", section: FINDING },
  { keys: "/", context: "global", action: "search", help: "Search this chat, or the chat list", section: FINDING },
  { keys: "n", context: "global", action: "searchNext", help: "Next match", section: FINDING },
  { keys: "N", context: "global", action: "searchPrev", help: "Previous match", section: FINDING },
  { keys: ":", context: "global", action: "commandLine", help: "Run a command (Tab completes)", section: FINDING },
  { keys: "?", context: "global", action: "help", help: "This sheet", section: FINDING },

  { keys: "<Space>n", context: "global", action: "newChat", help: "New chat", section: LEADER },
  { keys: "<Space>b", context: "global", action: "toggleChats", help: "Show or hide the chat list", section: LEADER },
  { keys: "<Space>d", context: "global", action: "deleteCurrentChat", help: "Delete this chat (asks first)", section: LEADER },
  { keys: "<Space>t", context: "global", action: "cycleTheme", help: "Next theme", section: LEADER },
  { keys: "<Space>,", context: "global", action: "settings", help: "Settings", section: LEADER },
  { keys: "<Space>r", context: "global", action: "restart", help: "Restart the agent", section: LEADER },
  { keys: "<Space>?", context: "global", action: "help", help: "Keys", section: LEADER },

  { keys: "j", context: "dialog", action: "dialogNext", help: "Next control", section: DIALOG, label: "j  l" },
  { keys: "l", context: "dialog", action: "dialogNext", help: "Next control", section: DIALOG, hidden: true },
  { keys: "k", context: "dialog", action: "dialogPrev", help: "Previous control", section: DIALOG, label: "k  h" },
  { keys: "h", context: "dialog", action: "dialogPrev", help: "Previous control", section: DIALOG, hidden: true },
  { keys: "<CR>", context: "dialog", action: "dialogActivate", help: "Choose it", section: DIALOG, label: "Enter" },
  { keys: "f", context: "dialog", action: "hints", help: "Label the dialog's controls", section: DIALOG },
  { keys: "q", context: "dialog", action: "dialogClose", help: "Close (Esc works too)", section: DIALOG },
];

/** Splits vim notation into keys: "<C-w>h" → ["<C-w>", "h"] */
export function parseKeys(keys: string): string[] {
  return keys.match(/<[^>]+>|./g) ?? [];
}

const parsed = new Map(BINDINGS.map((binding) => [binding, parseKeys(binding.keys)]));

const startsWith = (keys: string[], prefix: string[]) => prefix.every((key, index) => keys[index] === key);

/**
 * The binding `sequence` completes in `context`, if any, and whether it's the start of a longer one. The pane's own
 * bindings come first, then global ones (dialogs have only their own)
 */
export function lookup(context: Context, sequence: string[]): { exact?: Binding; continuations: Binding[] } {
  const candidates = BINDINGS.filter(
    (binding) => binding.context === context || (context !== "dialog" && binding.context === "global"),
  );
  // A pane binding hides a global one on the same keys
  const shadowed = new Set(candidates.filter((binding) => binding.context === context).map((binding) => binding.keys));
  const live = candidates.filter((binding) => binding.context === context || !shadowed.has(binding.keys));
  const exact = live.find((binding) => {
    const keys = parsed.get(binding)!;
    return keys.length === sequence.length && startsWith(keys, sequence);
  });
  const continuations = live.filter((binding) => {
    const keys = parsed.get(binding)!;
    return keys.length > sequence.length && startsWith(keys, sequence);
  });
  return { exact, continuations };
}

/** The keys left to press after `typed`, for the which-key popup */
export const remainingKeys = (binding: Binding, typed: number) => parsed.get(binding)!.slice(typed).join("");

const NAMED: Record<string, string> = {
  " ": "<Space>",
  Enter: "<CR>",
  Escape: "<Esc>",
  Tab: "<Tab>",
  Backspace: "<BS>",
  ArrowDown: "<Down>",
  ArrowUp: "<Up>",
  ArrowLeft: "<Left>",
  ArrowRight: "<Right>",
};

const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock", "Fn", "Hyper", "Super", "OS", "Dead", "Process", "Unidentified"]);

/** The physical key for Ctrl combinations, since Ctrl changes what some layouts report as the key */
function ctrlBase(event: KeyboardEvent): string {
  if (/^[a-z]$/i.test(event.key)) return event.key.toLowerCase();
  const code = /^(?:Key|Digit)(.)$/.exec(event.code);
  if (code) return code[1].toLowerCase();
  if (event.code === "BracketLeft") return "[";
  return event.key;
}

/** A keydown in vim notation ("j", "G", "<C-d>", "<Esc>"), or null for a lone modifier */
export function keyToken(event: KeyboardEvent): string | null {
  if (MODIFIERS.has(event.key)) return null;
  if (event.ctrlKey) {
    const base = ctrlBase(event);
    // Ctrl-[ is Esc and Ctrl-6 is Ctrl-^, as in vim
    if (base === "[") return "<Esc>";
    if (base === "6" || base === "^") return "<C-^>";
    return event.shiftKey ? `<C-S-${base}>` : `<C-${base}>`;
  }
  return NAMED[event.key] ?? (event.key.length === 1 ? event.key : null);
}

const SPOKEN: Record<string, string> = { "<Space>": "Space", "<CR>": "Enter", "<Esc>": "Esc", "<Tab>": "Tab" };

/** Vim notation as the status line and which-key show it: "<C-w>h" → "Ctrl-w h", "<Space>n" → "Space n", "gg" → "gg" */
export function displayKeys(keys: string): string {
  const parts = parseKeys(keys);
  const named = parts.some((key) => key.length > 1);
  return parts.map((key) => SPOKEN[key] ?? key.replace(/^<C-(.+)>$/, "Ctrl-$1")).join(named ? " " : "");
}
