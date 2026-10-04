# RadAgent

A personal Strands agent (Python, `agent/`) served over a WebSocket to a Tauri 2 app for macOS and iOS (`client/`),
deployed to Amazon Bedrock AgentCore Runtime with Terraform (`infra/`). Chats live in S3 on AWS, `agent/.agent/`
locally. `scripts/` deploys and sets things up; `server/` is optional self-hosted S3 (Garage).

Each folder has its own `CLAUDE.md` with its conventions; it loads when you work there. The READMEs are for
people; don't read them for orientation, this file and the folder ones cover it.

## Where things are

| You want to…                          | Start at                                                                    |
| ------------------------------------- | --------------------------------------------------------------------------- |
| Add or change an agent tool           | `agent/src/radagent/tools/<name>/tools.py`, registered in `tools/__init__.py` (skill `add-tool`) |
| Show the user something rich (a card) | `agent/src/radagent/cards.py` ↔ `client/src/cards/contract.ts` (skill `add-tool`) |
| Add a `/command`                      | `agent/src/radagent/commands.py` or a note like `coding.py`, plus `client/src/chat/commands.ts` (skill `add-slash-command`) |
| Add an app setting                    | `client/src/settings/definitions.ts` (skill `add-setting`)                  |
| Add an API key / secret               | `agent/.env` locally, `scripts/put-secrets.sh` for AWS (skill `add-secret`) |
| Change the WebSocket protocol         | `agent/src/radagent/server/core.py` (`dispatch`, `_forward`) ↔ `client/src/agent.ts` (`AgentEvent`) |
| Change how saved chats reopen         | `agent/src/radagent/server/history.py` ↔ `Turn`/`Part` in `client/src/agent.ts` |
| Model IDs, trusted domains            | `agent/src/radagent/config.py`                                              |
| Prompt-injection safety               | `agent/src/radagent/tools/web/trust_gate.py`                                |

Don't open these unless the task is about them: `client/src-tauri/gen/apple/**` (generated Xcode project),
`*.lock`, `bun.lock`, `uv.lock`, `Cargo.lock`, `.terraform.lock.hcl`, `client/src/keys/controller.ts` (1000+ lines;
the keymap is data in `keys/keymap.ts`). Grep for a symbol before reading a whole file.

## Commands

```sh
cd agent && uv sync && uv run radagent --dev          # agent on 127.0.0.1:8787 (what `bun tauri dev` connects to)
cd agent && uv run radagent --repl                    # chat in the terminal
cd client && bun install && bun tauri dev             # the app, hot reload
uv run --project agent python scripts/smoke_ws.py --prompt "hi"   # agent over the WebSocket, no app
```

There is no test suite and no linter config. CI (`.github/workflows/main.yml`, on main only) compiles; run the
same checks before a PR with skill `verify`. Bedrock, Spotify, Google etc. aren't reachable from a dev container, so
check behavior with throwaway scripts that stub the network/model (kept out of the repo) and say what wasn't tested.

## Workflow

- Branch `feat/<thing>`, `fix/<thing>`, `ci/<thing>` or `docs/<thing>` off `staging`; PRs go to **staging**.
  `staging` → `main` is merged separately, and every push to main deploys `agent/` to AgentCore. Skill `ship`.
- Commit subjects: `feat: …`, `fix: …`, `fix(infra): …`, `ci: …`, lower case, no period, saying what the user
  gets ("feat: youtube search tool"). A body only when the why isn't obvious.
- A feature usually spans agent + client + README in one commit; keep the contract files on both sides in step in
  the same change.
- Update the README section a feature belongs to (root `README.md` for app behavior and keys, `agent/README.md`
  for agent setup like Spotify, `infra/README.md` for deploy steps). Don't add new docs files.

## Conventions everywhere

- Comments and docstrings explain *why* and how pieces connect, in plain sentences, and name the file on the other
  side of a contract ("Keep these types in step with `client/src/cards/contract.ts`"). No restating the code.
- Prefer one obvious extension point (a list, a dict, a registry entry) over new wiring; most features in history
  were "add an entry here, and here".
- Anything from the web or a third-party account (pages, search results, playlist names, Drive files) is
  untrusted: register the tool with the trust gate. See `agent/CLAUDE.md`.
- Secrets never go into Terraform state, argv, logs or the repo.
