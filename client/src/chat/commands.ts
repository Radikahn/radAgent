/** A slash command typed at the start of a message; the agent gets its name as the prompt's `command` */
export type Command = {
  name: string;
  /** What the composer says it does */
  hint: string;
  /** Sent when the command is used on its own, with nothing after it */
  fallback?: string;
  /** Can be sent on its own, with no text; the agent decides what that means */
  bare?: boolean;
};

export const COMMANDS: Command[] = [
  {
    name: "memory",
    hint: "Look through your other chats for this message",
    fallback: "What do you remember about me from our other chats?",
  },
  {
    // The agent answers as usual, asked for code (agent/src/radagent/coding.py); chat/CodeBlock.tsx draws the blocks
    name: "code",
    hint: "Write code, in boxes you can copy",
  },
  {
    // Runs agent/src/radagent/tools/research; its progress renders through chat/CommandPart.tsx
    name: "research",
    hint: "Send a crew of agents across the web and get back a cited report",
  },
  {
    // Kept in your profile, which every chat knows (agent/src/radagent/profile.py); on its own it shows the profile
    name: "profile",
    hint: "Tell every chat something about you to remember; on its own, see what it knows",
    bare: true,
  },
];

/** The command a message starts with, if any, and the text to send with it */
export function parseCommand(input: string): { text: string; command?: Command } {
  const match = /^\/(\w+)(?:\s+([\s\S]*))?$/.exec(input.trim());
  const command = match ? COMMANDS.find((candidate) => candidate.name === match[1].toLowerCase()) : undefined;
  if (!match || !command) return { text: input.trim() };
  return { text: match[2]?.trim() || command.fallback || "", command };
}

/** Commands matching what's typed so far, while the user is still typing a command's name */
export function suggestCommands(input: string): Command[] {
  const match = /^\/(\w*)$/.exec(input);
  if (!match) return [];
  const typed = match[1].toLowerCase();
  return COMMANDS.filter((command) => command.name.startsWith(typed) && command.name !== typed);
}
