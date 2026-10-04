---
name: add-slash-command
description: Add a /command to radagent (typed at the start of a message in the app or REPL). Use when asked for a new slash command or to change how /code, /memory or /research behave. Explains the two kinds of command and every file each one touches.
---

# Adding a slash command

The client parses `/name args` (`client/src/chat/commands.ts`) and sends `command: "name"` with the prompt text.
On the agent, `server/core.py` `Chats.prompt` routes it one of two ways. Pick the kind first:

## Kind A: note command (the agent answers as usual, with extra instructions or permissions)

Examples: `/code` (`agent/src/radagent/coding.py`, commit `02b2156`), `/memory` (`tools/chats/`).

1. A module with `X_NOTE: str = "<x_request>…</x_request>"` and `is_x_note(text)` checking the opening tag.
   The note is sent as its own content block ahead of the prompt.
2. `agent.py`: a flag on `RadAgent.stream()` (and `query()`) that appends the note via `_with_notes`; add the note
   check to `_is_note` so memory extraction doesn't learn it as the user's words.
3. If the command unlocks tools for one turn, pass a flag in `invocation_state` (see `CROSS_CHAT`) and have the
   tools refuse without it; the tools themselves stay registered every turn.
4. `server/core.py` `_run_turn`: pass the flag from `command == "x"`.
5. `server/history.py`: add `"x": is_x_note` to `NOTES` so a reopened chat hides the note and shows the chip.
6. `repl/repl_dev.py` if the REPL should support it.

## Kind B: runner command (runs outside the agent loop, streams its own events)

Example: `/research` (`commands.py`, `tools/research/`).

1. `agent/src/radagent/commands.py`: an `async def _x(run: CommandRun) -> str` and a `Command(...)` entry in
   `COMMANDS`. Emit progress with `run.emit(event)`; record the exchange with `remember(...)` on success,
   failure *and* cancellation, passing any source URLs so the trust gate sees them. `keep` trims the event timeline
   to what a reopened chat replays. Check `Command`'s current fields first; they grow over time.
2. Event shapes in a module of their own (see `tools/research/events.py`), mirrored in the client.
3. Client: a reducer/replay for its `command_event`s, wired in `chat/CommandPart.tsx`.

## Both kinds

- `client/src/chat/commands.ts`: an entry in `COMMANDS` with `name`, `hint` (what the composer shows) and a
  comment saying where it's implemented; `fallback` if it makes sense with nothing after it.
- Model config (if it runs its own agents): a `X_MODEL: str | None` in `config.py`, `None` = conversation's model.
- A short section in the root `README.md` with an example message.
- Skill `verify`; then exercise it through `server.core.dispatch` with a fake client and the model stubbed.
