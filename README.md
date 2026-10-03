# RadAgent

A Python Strands agent baseline that is meant to be modded, with a Tauri app for macOS and iOS. The agent runs on
Amazon Bedrock AgentCore Runtime and keeps chats in S3, so the Mac and the iPhone share them; for development it
runs on your machine instead.

| Folder     | What                                                                   |
| ---------- | ---------------------------------------------------------------------- |
| `agent/`   | Python Strands agent (uv project, package in `agent/src/radagent`), served over a WebSocket |
| `client/`  | Tauri 2 app for macOS and iOS (Rust in `client/src-tauri`, React + TS + Vite in `client/src`) |
| `infra/`   | Terraform for AWS: AgentCore runtime, S3, Cognito, ECR, Secrets Manager; see [infra/README.md](infra/README.md) |
| `scripts/` | Deploying the agent, setting up the user and secrets, installing the apps, smoke tests |
| `server/`  | Docker Compose for Garage, a self-hosted S3, if you'd rather keep chats off AWS |

## Agent

```sh
cd agent
uv sync
uv run radagent
```

## App

The app talks to the agent over a WebSocket (`agent/src/radagent/server`), the contract AgentCore Runtime
expects. For development, run both on this machine; the development build connects to `ws://127.0.0.1:8787/ws`
(`client/.env.development`) with no sign-in:

```sh
cd agent && uv run radagent --dev                   # the agent on 127.0.0.1:8787
cd client && bun install && bun tauri dev           # the app, with hot reload
```

`uv run --project agent python scripts/smoke_ws.py --prompt "hi"` checks the agent without the app.

### On AWS

Deploying is in [infra/README.md](infra/README.md): Terraform, then `scripts/deploy-agent.sh` to build and push the
agent's arm64 image and point the runtime at it, then `scripts/client-env.sh`, which writes the runtime's address
into `client/.env.production`. After that, GitHub Actions checks every push to main and deploys the agent when
`agent/` changed. Release builds use it and sign in with the Cognito user from
`scripts/create-user.sh`; the sign-in lasts 90 days and is kept in the Keychain.

- **Mac:** `scripts/install-mac.sh` builds the app, ad-hoc signed, and copies it into `/Applications`.
- **iPhone, with a free Apple ID:** sign in to Xcode (Settings > Accounts) and turn on Developer Mode on the phone,
  then `APPLE_DEVELOPMENT_TEAM=<team id> scripts/install-ios.sh "<device>"`. A free signature lasts 7 days, so run it
  again weekly; reinstalling keeps you signed in. iOS builds need Xcode's iOS platform
  (`xcodebuild -downloadPlatform iOS`).

Both devices join the same runtime session, so a reply started on one streams on the other. A reply keeps running
when the phone sleeps or the connection drops (AgentCore also closes connections after an hour); the app reconnects
and shows it as saved.

| Key           | Does                                                      |
| ------------- | --------------------------------------------------------- |
| Enter         | Send (Shift+Enter for a new line; on a phone, Return is a new line) |
| Esc           | Leave the message box; outside it, stop the answer        |
| Ctrl+C        | Stop the answer, from anywhere                            |
| ⌘N / Ctrl+N   | New chat                                                  |
| ⌘B / Ctrl+B   | Show or hide the chat list                                |
| ⌘, / Ctrl+,   | Settings                                                  |
| ?             | Every key and command (outside the message box)           |

### Keyboard

On desktop the whole app works from the keyboard, the way vim does (phones and tablets keep the plain touch
app). Typing a message is insert mode; Esc switches to normal mode, where keys move around instead of typing,
and `i` goes back to the message box. The corner under the input shows the mode. In normal mode:

- `j` / `k` step through the chat a block at a time (a paragraph, list item, code block, card or message),
  `{` / `}` by message, `gg` / `G` to either end, `Ctrl-d` / `Ctrl-u` by half a screen. Counts work: `3j`.
- `Enter` opens what's in the block; `f` labels everything clickable on screen, and typing a label clicks it.
- `yy` copies the block, `Y` the whole reply as Markdown, `y` any text selected with the mouse; `p` puts it in
  the message box.
- `Ctrl-h` goes to the chat list (`j` / `k`, `Enter` to open, `dd` to delete), `Ctrl-l` back, `Ctrl-j` to the
  input; `gt` / `gT` switch chats from anywhere, and `Ctrl-^` goes back to the last one.
- `/` searches the chat or the list (`n` / `N` for the next match); `:` runs commands such as `:b <title>`,
  `:new`, `:set theme=dark` and `:q`, with Tab completion; `Space` opens a menu of shortcuts.

The keymap is data in `client/src/keys/keymap.ts`, which also feeds the help sheet and the popup that lists what
can follow a half-typed key. The layer finds blocks and buttons by class name (`client/src/keys/dom.ts`), so new
UI is reachable with `f` without any wiring. In normal mode `Ctrl-b` scrolls up, as in vim; use ⌘B or `Space b`
for the chat list.

### Settings

The gear in the bottom-left corner opens the settings, which are listed in `client/src/settings/definitions.ts`.
Adding one is one entry there: the modal draws a row for it, its value is kept in localStorage, and its `apply`
puts it into effect at startup and on every change. Read values anywhere with `settings.get()` (and
`settings.subscribe()`), or `useSettings()` in React; the store itself is plain TypeScript. Settings come in the
kinds in `schema.ts` (`choice` and `toggle` so far); a new kind gets a control in `SettingsModal.tsx`.

### Chats and memory

Each chat is its own conversation with its own context and memory, kept in `agent/.agent/chats/<id>/`: the saved
conversation (reopening a chat picks up where it left off), the facts the agent learned in it, and the cards it
showed. A chat only remembers what was said in it. Deleting a chat deletes its memory too.

On AWS the chats are in the S3 bucket instead (`RADAGENT_S3_BUCKET`, set by Terraform), under `chats/`, and the
shared memory under `memory/`; `scripts/migrate-chats.sh` copies the local ones up, since the layout in the bucket
is the same as the folder's. To keep them on your own server instead, run Garage from `server/`; see
[server/README.md](server/README.md).

Start a message with `/memory` to let the agent look through your other chats for that one message, e.g.
`/memory what coffee shop did I like?`. On its own, `/memory` asks what it remembers about you. It also searches
`agent/.agent/memory`, the shared memory from before there were chats. If one of those chats read untrusted web
content, pulling text out of it turns off shell, write and edit in the current chat, the same as reading that
content directly would.
