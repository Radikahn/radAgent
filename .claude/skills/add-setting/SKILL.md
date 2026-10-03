---
name: add-setting
description: Add a user setting to the radagent app's Settings modal. Use when asked for a new preference, toggle or option in the app.
---

# Adding an app setting

Settings are client-only and data-driven; one entry usually does it.

1. `client/src/settings/definitions.ts`: add a key to `definitions` using a kind from `schema.ts`
   (`choice({...})` or `toggle({...})` so far) with `section`, `label`, `default`, and `apply(value)` that puts
   it into effect (it runs at startup and on every change). The key is the stored name: renaming it resets users
   to the default.
2. Read it with `settings.get().key` / `settings.subscribe()` in plain TS, or `useSettings()` in React.
3. A new kind of control: add it to `schema.ts` and render it in `SettingsModal.tsx`.
4. If the agent needs the value, it isn't a setting here: it goes in the prompt message or a new protocol field
   (`server/core.py` `dispatch` ↔ `client/src/agent.ts`).
5. If it's reachable from `:set` in the keyboard layer, check `client/src/keys/ex.ts`.

Mention it in the root `README.md` "Settings" section only if it changes behavior people would look for.
Verify with `cd client && bun run build`.
