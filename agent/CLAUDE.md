# agent/

Python 3.13, uv project, package `radagent` in `src/radagent`. Built on `strands` + `strands_harness`
(`create_harness`), which supplies the built-in tools (shell, read, write, edit, web_search via Exa, subagent…),
memory, sessions and context offloading. Run everything from `agent/` (`uv run …`); `.env` here holds local keys.

## Map

| File                         | Does                                                                          |
| ---------------------------- | ----------------------------------------------------------------------------- |
| `main.py`                    | CLI: `--repl`, `--serve`, `--dev`, `--spotify-login`; loads secrets before importing the agent |
| `agent.py`                   | `RadAgent`: builds the harness per chat (tools, trust gate, session, memory, offloader), `stream()` |
| `config.py`                  | Model IDs (`MODEL`, research models), `TRUSTED_DOMAINS`                       |
| `tools/__init__.py`          | `TOOLS`, the list of custom tools; a suite exports its own list (`SPOTIFY_TOOLS`) |
| `cards.py`                   | `TypedDict`s for cards the client renders; `is_card()`                        |
| `commands.py`                | Slash commands that run outside the agent loop (`/research`); `remember()`    |
| `coding.py`, `tools/chats/`  | Note-style commands (`/code`, `/memory`): a note block ahead of the prompt     |
| `server/core.py`             | `Hub`, `Chats`, `dispatch` (client → server), `_forward` (stream → client events) |
| `server/history.py`          | Saved conversation → client turns; hides command notes                         |
| `server/settings.py`         | Secrets Manager → environment on AWS                                           |
| `chats.py`, `storage.py`     | `ChatStore` over `Files` (local folder or S3, same layout)                     |
| `tools/web/trust_gate.py`    | `TrustGate`: taints a chat after untrusted content and blocks shell/read/write/edit |
| `media/`                     | Attachments → model content, within Bedrock's size limits                      |
| `prompts/system_prompt.txt`  | Default prompt; it ends on a heading that `append_tools` fills with every tool's first sentence |

## How a tool works

- `@tool async def name(...) -> AsyncIterator[dict[str, Any]]` (async generator) when it shows a card: `yield card`
  first, then **the last yield is the result the model sees**:
  `{"status": "success" | "error", "content": [{"text": ...}]}`. Plain `def` is fine without a card.
- The docstring *is* the tool spec. First sentence = what it does (it's the line in the system prompt's tool list);
  then when to use it and what the user already sees. `Args:` documents each parameter for the model.
- Blocking I/O goes through `await asyncio.to_thread(...)`. HTTP is stdlib `urllib.request` with a `TIMEOUT_S`;
  don't add dependencies for what the stdlib does.
- Clamp and normalize inputs (`limit = min(max(limit, 1), MAX_X)`, `" ".join(query.split())`). Return errors as an
  error result that tells the model what to try next; don't raise.
- Keep the model's result small: a summary that says the user already sees the card, so don't repeat it. Results
  over ~1,500 tokens are offloaded by the harness. Cards never go in the result.
- Tools that read the web or anything a third party can write go in the trust gate (`_FIXED_SOURCE_TOOLS` with the
  source URL, or URLs recorded from the result). Missing this is a security bug.
- The tool list must not change between turns (prompt cache). Gate per turn with `invocation_state` flags
  (see `tools/chats`, `CROSS_CHAT`) instead of adding/removing tools.

## Style

Match the surrounding code exactly; it is consistent:

- Spaces around `=` in keyword arguments and defaults: `urlopen(request, timeout = TIMEOUT_S)`,
  `def f(limit: int = 5)`. Annotated module constants: `MAX_VIDEOS: int = 10`, with a comment saying why the value.
- Type hints everywhere, `X | None`, `collections.abc` types, `TypedDict` for shapes that cross a boundary.
- Private helpers start with `_`. Two blank lines between functions, three before a new section; sections may get a
  `# ---- Name ----` header. Imports stdlib, third-party, then `radagent.*`.
- Docstrings: a one-line summary without a trailing period, then prose; `Args:` as `name: {type} description`.
- Imports that are slow or need secrets loaded first happen inside functions (see `main.py`).
- Print diagnostics to stderr prefixed `[radagent]`.

## Checks

```sh
uv sync --locked
uv run --locked python -m compileall -q src
uv run --locked python -c "import radagent.main, radagent.server.app, radagent.repl, radagent.tools"
```

The import check catches a tool that fails to register. For behavior, write a throwaway script that calls the
tool function with the network stubbed (`unittest.mock.patch` on `urlopen` or the client), or drives
`server.core.dispatch` against a fake client; mocked S3 via moto. Don't commit these.
