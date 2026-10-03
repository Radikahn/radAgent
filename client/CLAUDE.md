# client/

Tauri 2 app for macOS and iOS: React 19 + TypeScript (strict) + Vite in `src/`, Rust in `src-tauri/`. Bun is the
package manager (`bun install`, `bun run build`, `bun tauri dev`). No UI framework, no state library, no CSS
framework: plain React state/reducers and a CSS file per area.

## Map

| Path                     | Does                                                                              |
| ------------------------ | --------------------------------------------------------------------------------- |
| `src/agent.ts`           | `AgentEvent` (server protocol), `Turn`/`Part`, the reducer and `useAgent`         |
| `src/remote/`            | WebSocket connection, Cognito sign-in, Keychain secrets via Rust commands          |
| `src/chat/TurnView.tsx`  | Renders a turn's parts; `TOOL_LABELS` gives each tool its running/done label       |
| `src/chat/commands.ts`   | `COMMANDS`, the slash commands the composer knows                                  |
| `src/chat/CommandPart.tsx` | Live parts of runner commands (`/research`)                                     |
| `src/cards/`             | `contract.ts` (types + `isXCard` guards), `index.tsx` (`CardView`), one `XCard.tsx` each, `cards.css` |
| `src/settings/`          | `definitions.ts` (every setting), `schema.ts` (kinds), store and modal             |
| `src/keys/`              | Vim-style keyboard layer; `keymap.ts` is data, `dom.ts` finds things by class name |
| `src/research/`          | `/research` UI and report export                                                   |
| `src-tauri/src/lib.rs`   | Tauri commands (Keychain, export); `keyboard.rs` is iOS-only                       |
| `src-tauri/tauri.conf.json` | CSP: every image/connect host the app loads must be listed in both `csp` and `devCsp` |

## Conventions

- Contracts with the agent are typed here and in Python and kept in step in the same change; each type
  comments where its other half is. Data arriving from the agent is `unknown` until a type guard checks
  `kind` + `version`; unknown or old shapes render nothing rather than guess.
- External links go through `<External href>` (`cards/External.tsx`) so they open in the system browser; only
  `https:` URLs from a card get opened.
- The keyboard layer reaches new UI by class name: a new steppable block gets its selector in `BLOCKS` in
  `keys/dom.ts`; anything clickable (`a[href]`, `button`, `[role=button]`…) gets `f` hints automatically.
- Phones keep the touch app; keyboard-only behavior is desktop.
- Reuse existing class names and CSS variables before adding new ones (cards share `places-header`,
  `places-strip`). Theme comes from `data-theme` on `<html>` and `color-scheme`; support light and dark.
- Doc comments `/** … */` on exported types and fields that need explaining; `//` for the why inside code.
- `tsconfig` has `noUnusedLocals`/`noUnusedParameters`: remove what you stop using.
- `src-tauri` has no platform-specific code except `#[cfg(target_os = "ios")]` modules; keep it that way so
  `cargo check` on Linux covers it.

## Checks

```sh
bun install --frozen-lockfile && bun run build                          # tsc + vite, what CI runs
cd src-tauri && cargo check --locked --all-targets                      # needs libwebkit2gtk-4.1-dev on Linux
```

To see UI, run the agent with `--dev` and `bun run dev` (Vite on :1420), then drive it with Playwright's headless
Chromium. Tauri APIs (`openUrl`, Keychain) aren't available in a plain browser.
