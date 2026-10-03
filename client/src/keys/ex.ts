// `:` commands, with vim's names where vim has one (:b, :bd, :ls, :set, :noh, :q)

import type { ChatSummary } from "../agent";
import type { Setting } from "../settings/schema";
import { settings } from "../settings/store";

/** What commands can do; the keyboard layer provides it */
export type ExApi = {
  chats(): ChatSummary[];
  openChat(id: string): void;
  altChat(): void;
  cycleChat(step: 1 | -1): void;
  newChat(): void;
  deleteCurrentChat(force: boolean): void;
  showChats(): void;
  stop(): void;
  restart(): void;
  quit(force: boolean): void;
  openSettings(): void;
  clearSearch(): void;
  help(): void;
  gotoMessage(n: number): void;
  message(text: string, error?: boolean): void;
};

type ExCommand = {
  names: string[];
  /** Shown after the name in completions, e.g. "{chat}" */
  args?: string;
  help: string;
  run(api: ExApi, arg: string, bang: boolean): void;
  hidden?: boolean;
};

/** A chat by number, by `#` for the previous one, or by part of its title */
function findChat(api: ExApi, query: string): ChatSummary | "alternate" | null {
  if (query === "#") return "alternate";
  const chats = api.chats();
  if (/^\d+$/.test(query)) return chats[Number(query) - 1] ?? null;
  const needle = query.toLowerCase();
  return chats.find((chat) => chat.title.toLowerCase().includes(needle)) ?? null;
}

function openChat(api: ExApi, query: string) {
  if (!query) return api.message("E471: Argument required: which chat?", true);
  const chat = findChat(api, query);
  if (chat === "alternate") return api.altChat();
  if (!chat) return api.message(`E94: No matching chat for ${query}`, true);
  api.openChat(chat.id);
}

// `background` is vim's name for light or dark, so :set bg=dark works as a vim user would type it
const OPTION_ALIASES: Record<string, string> = { bg: "theme", background: "theme" };

const definitions = settings.definitions as Record<string, Setting>;

function describe(key: string): string {
  return `${key}=${String(settings.get()[key as keyof ReturnType<typeof settings.get>])}`;
}

/** :set name=value, :set name?, :set name / noname / name! for switches; :set alone opens the settings */
function set(api: ExApi, arg: string) {
  if (!arg) return api.openSettings();
  const shown: string[] = [];
  const known = (name: string) => (OPTION_ALIASES[name] ?? name) in definitions;
  for (const expression of arg.split(/\s+/)) {
    const match = /^([a-z]+)(\?|!|[=:](.*))?$/i.exec(expression);
    if (!match) return api.message(`E518: Unknown option: ${expression}`, true);
    const [, word, suffix, value] = match;
    // "no" and "inv" switch an option off or flip it, unless they're the start of an option's own name
    const negated = known(word) ? null : /^(no|inv)(.+)$/.exec(word);
    const prefix = negated && known(negated[2]) ? negated[1] : "";
    const name = prefix ? negated![2] : word;
    const key = OPTION_ALIASES[name] ?? name;
    const setting = definitions[key];
    if (!setting) return api.message(`E518: Unknown option: ${expression}`, true);
    const write = (next: unknown) => settings.set(key as never, next as never);

    if (setting.kind === "toggle") {
      if (suffix === "?") shown.push(describe(key));
      else if (value !== undefined) return api.message(`E474: Invalid argument: ${expression}`, true);
      else if (prefix === "inv" || suffix === "!") write(!settings.get()[key as never]);
      else write(prefix !== "no");
      continue;
    }

    if (value === undefined || prefix) {
      shown.push(describe(key));
      continue;
    }
    const option = setting.options.find((candidate) => candidate.value === value.toLowerCase());
    if (!option) {
      const choices = setting.options.map((candidate) => candidate.value).join(", ");
      return api.message(`E474: Invalid argument: ${expression} (${choices})`, true);
    }
    write(option.value);
    shown.push(describe(key));
  }
  if (shown.length) api.message(shown.join("  "));
}

export const EX_COMMANDS: ExCommand[] = [
  { names: ["new", "enew"], help: "New chat", run: (api) => api.newChat() },
  { names: ["b", "buffer", "e", "edit"], args: "{chat}", help: "Open a chat by part of its title, its number, or # for the last one", run: (api, arg) => openChat(api, arg) },
  { names: ["bn", "bnext"], help: "Next chat", run: (api) => api.cycleChat(1) },
  { names: ["bp", "bprevious", "bN", "bNext"], help: "Previous chat", run: (api) => api.cycleChat(-1) },
  { names: ["bd", "bdelete"], help: "Delete this chat (asks first; ! doesn't)", run: (api, _, bang) => api.deleteCurrentChat(bang) },
  { names: ["ls", "buffers", "files", "chats"], help: "Show the chat list", run: (api) => api.showChats() },
  { names: ["set", "se"], args: "{option}={value}", help: "Change a setting, e.g. :set theme=dark; alone, open settings", run: (api, arg) => set(api, arg) },
  { names: ["options", "settings"], help: "Open settings", run: (api) => api.openSettings() },
  { names: ["noh", "nohlsearch"], help: "Clear search highlights", run: (api) => api.clearSearch() },
  { names: ["stop"], help: "Stop the reply", run: (api) => api.stop() },
  { names: ["restart"], help: "Restart the agent", run: (api) => api.restart() },
  { names: ["h", "help"], help: "Keys and commands", run: (api) => api.help() },
  { names: ["q", "quit", "qa", "qall", "wq", "wqa", "x", "xa"], help: "Quit radAgent (! even while a reply is coming in)", run: (api, _, bang) => api.quit(bang) },
  { names: ["w", "write", "wa"], help: "Chats save as you go", run: (api) => api.message("Chats save as you go"), hidden: true },
];

/** Runs a command line (without its colon) */
export function runEx(api: ExApi, line: string) {
  const input = line.trim();
  if (!input) return;
  if (/^\d+$/.test(input)) return api.gotoMessage(Number(input));
  const match = /^([a-zA-Z]+)(!?)\s*(.*)$/.exec(input);
  // Like vim, any unambiguous start of a name works: :rest for :restart
  const abbreviated = match && EX_COMMANDS.filter((candidate) => candidate.names.some((name) => name.startsWith(match[1])));
  const command =
    match && (EX_COMMANDS.find((candidate) => candidate.names.includes(match[1])) ?? (abbreviated?.length === 1 ? abbreviated[0] : undefined));
  if (!match || !command) return api.message(`E492: Not an editor command: ${input}`, true);
  command.run(api, match[3].trim(), match[2] === "!");
}

export type Completion = { value: string; label: string; hint?: string };

/** What Tab can complete the line to: command names, then chat titles after :b, option names and values after :set */
export function complete(line: string, chats: ChatSummary[]): Completion[] {
  const argument = /^(\S+)\s+(.*)$/.exec(line);
  if (!argument) {
    return EX_COMMANDS.filter((command) => !command.hidden)
      .map((command) => ({ command, name: command.names.find((name) => name.startsWith(line)) }))
      .filter((entry): entry is { command: ExCommand; name: string } => entry.name !== undefined)
      .map(({ command, name }) => ({
        value: command.args ? `${name} ` : name,
        label: command.args ? `${name} ${command.args}` : name,
        hint: command.help,
      }));
  }
  const [, name, rest] = argument;
  if (["b", "buffer", "e", "edit"].includes(name)) {
    const needle = rest.toLowerCase();
    return chats
      .map((chat, index) => ({ chat, index }))
      .filter(({ chat }) => chat.title.toLowerCase().includes(needle))
      .map(({ chat, index }) => ({ value: `${name} ${chat.title}`, label: chat.title, hint: String(index + 1) }));
  }
  if (["set", "se"].includes(name) && !/\s/.test(rest)) {
    const [key, typed] = rest.split(/[=:]/);
    const setting = definitions[OPTION_ALIASES[key] ?? key];
    if (typed !== undefined && setting?.kind === "choice") {
      return setting.options
        .filter((option) => option.value.startsWith(typed.toLowerCase()))
        .map((option) => ({ value: `${name} ${key}=${option.value}`, label: `${key}=${option.value}`, hint: option.label }));
    }
    return Object.entries(definitions)
      .filter(([candidate]) => candidate.startsWith(key))
      .map(([candidate, option]) => ({
        value: `${name} ${candidate}${option.kind === "choice" ? "=" : ""}`,
        label: candidate,
        hint: option.label,
      }));
  }
  return [];
}
