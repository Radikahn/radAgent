---
name: add-tool
description: Add a new agent tool (or tool suite) to radagent, optionally with a card the app renders. Use when asked for a new capability the agent calls, e.g. "search X", "control Y", "show Z as a card". Lists every file to touch so you don't have to rediscover the wiring.
---

# Adding an agent tool

The canonical example is `search_youtube` (commit `781ad12`): read `agent/src/radagent/tools/youtube/tools.py`
as the template instead of exploring other tools. For a multi-tool suite with an API client and OAuth, the
template is `tools/spotify/` (commit `80bced5`).

## 1. Agent side (always)

1. `agent/src/radagent/tools/<name>/tools.py`: the tool(s). Follow the "How a tool works" rules in
   `agent/CLAUDE.md` (async generator if it yields a card, last yield is the model's result, docstring is the spec,
   `asyncio.to_thread` for blocking I/O, errors as results that suggest a next step, small summary).
2. `agent/src/radagent/tools/<name>/__init__.py`: re-export, with `__all__`. A suite exports a list
   (`SPOTIFY_TOOLS`), ordered: reads first, then actions, then changes to the user's account.
3. `agent/src/radagent/tools/__init__.py`: import it and add it to `TOOLS`.
4. **Trust gate** (`agent/src/radagent/tools/web/trust_gate.py`): if anything in the result can be written by
   someone other than the user (web pages, search results, comments, titles, descriptions, shared files), add each
   reading tool to `_FIXED_SOURCE_TOOLS` with its source URL. If unsure, add it.
5. Keys: if it needs an API key or token, follow skill `add-secret`.
6. Tools that need per-chat context (the chat id, the store) are built in `RadAgent.__init__` like
   `chat_tools(chats, chat_id)`, not put in `TOOLS`. Never make the tool list vary turn to turn.

The system prompt's tool list is generated from each tool's first docstring sentence; don't edit
`system_prompt.txt` to mention the tool.

## 2. Card (only if the user should see results as UI)

Both sides, same change, same field names and comments:

1. `agent/src/radagent/cards.py`: `class XItem(TypedDict)` + `class XCard(TypedDict)` with
   `card: Literal["x"]`, `version: Literal[1]`. Comment each field with its format/example.
2. `client/src/cards/contract.ts`: the matching types (nullable `str | None` → `string | null`), add to the
   `Card` union, and `isXCard()` checking `card`, `version` and the array field.
3. `client/src/cards/XCard.tsx`: `XCardView({ card })`. Filter to `https:` URLs, return `null` when empty,
   links via `<External>`, `loading="lazy"` on images, an `aria-label` on the section. Reuse `places-header` /
   `places-strip` for a horizontal strip.
4. `client/src/cards/index.tsx`: import and add a line to `CardView`.
5. `client/src/cards/cards.css`: styles, using the existing CSS variables; check light and dark.
6. `client/src/keys/dom.ts`: add the item's class (e.g. `.video`) to `BLOCKS` so `j`/`k` step through it.
7. `client/src-tauri/tauri.conf.json`: add any image host to `img-src` in **both** `csp` and `devCsp`.

The server forwards cards and saves them with the chat on its own (`server/core.py`); no protocol change needed.
Breaking a card's shape later means bumping `version` on both sides.

## 3. Client label (always)

`client/src/chat/TurnView.tsx`, `TOOL_LABELS`: `tool_name: ["Doing it", "Did it"]`, in user terms.

## 4. Docs

A line or section in the README the feature belongs to (root `README.md` for what the user can do,
`agent/README.md` for setup such as creating an API app and getting keys), including any limits and that its
results count as untrusted if they do.

## 5. Verify

Skill `verify`. Then call the tool function directly in a scratch script with the HTTP call mocked, using a saved
real response if you can get one, and check the card and the summary text.
