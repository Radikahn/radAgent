import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createKeyboard, type AppApi, type Keyboard, type KeyboardState, type LineKind } from "./controller";
import { EX_COMMANDS } from "./ex";
import { BINDINGS, displayKeys, remainingKeys, type Binding } from "./keymap";
import "./keys.css";

const MODE_LABELS = { hints: "HINT", ":": "COMMAND", "/": "SEARCH", help: "HELP", insert: "INSERT", normal: "NORMAL" };

/** Vim's bottom line: messages and questions on the left, then keys typed so far, the mode, and where the cursor is */
function StatusLine({ state }: { state: KeyboardState }) {
  const mode = state.hints ? "hints" : (state.line ?? (state.help ? "help" : state.mode));
  const where =
    mode === "normal" && (state.pane === "thread" || state.pane === "chats")
      ? `${state.pane === "chats" ? "chats" : "chat"}${state.position ? ` ${state.position}` : ""}`
      : null;
  return (
    <div className="vim-status" data-vim-ui>
      <span className="vim-said" role="status">
        {state.confirm ? (
          <span className="vim-confirm">{state.confirm}</span>
        ) : (
          state.message && (
            <span key={state.message.text} className={`vim-message materialize ${state.message.error ? "error" : ""}`}>
              {state.message.text}
            </span>
          )
        )}
      </span>
      {state.pending && <span className="vim-pending">{state.pending}</span>}
      <span className={`vim-mode mode-${mode === ":" ? "command" : mode === "/" ? "search" : mode}`}>{MODE_LABELS[mode]}</span>
      {where && <span className="vim-where">{where}</span>}
    </div>
  );
}

/** What can follow a half-typed key sequence, like which-key.nvim */
function WhichKey({ typed, bindings, pending }: { typed: number; bindings: Binding[]; pending: string }) {
  return (
    <div className="vim-which-key materialize" data-vim-ui aria-hidden="true">
      <div className="vim-which-title">{pending}</div>
      {bindings.map((binding) => (
        <div key={`${binding.context}:${binding.keys}`} className="vim-which-row">
          <kbd>{displayKeys(remainingKeys(binding, typed))}</kbd>
          <span>{binding.help}</span>
        </div>
      ))}
    </div>
  );
}

/** A label on everything clickable. It goes in the top layer, so labels show over an open dialog too */
function HintLayer({ hints }: { hints: NonNullable<KeyboardState["hints"]> }) {
  const layer = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = layer.current;
    try {
      element?.showPopover();
    } catch {
      // Without the popover API it's a plain overlay above the page
      element?.removeAttribute("popover");
    }
  }, []);
  return (
    <div ref={layer} className="vim-hints" popover="manual" data-vim-ui aria-hidden="true">
      {hints.items.map(
        (hint) =>
          !hint.hidden &&
          hint.label.startsWith(hints.typed) && (
            <span
              key={hint.label}
              className="vim-hint"
              style={{ left: Math.min(Math.max(hint.left - 6, 2), window.innerWidth - 36), top: Math.max(hint.top - 8, 2) }}
            >
              <span className="vim-hint-typed">{hints.typed}</span>
              {hint.label.slice(hints.typed.length)}
            </span>
          ),
      )}
    </div>
  );
}

/** The `:` and `/` line, floating above the input. Tab completes commands, ↑ and ↓ go through earlier lines */
function CommandLine({ kind, keyboard }: { kind: LineKind; keyboard: Keyboard }) {
  const [value, setValue] = useState("");
  // Completions match what was typed, so pressing Tab again moves through them instead of narrowing to one
  const [typed, setTyped] = useState("");
  const [choice, setChoice] = useState(-1);
  const [found, setFound] = useState<number | null>(null);
  const [back, setBack] = useState(0);
  const completions = useMemo(() => (kind === ":" ? keyboard.completions(typed).slice(0, 8) : []), [kind, keyboard, typed]);

  const change = (next: string) => {
    setValue(next);
    setTyped(next);
    setChoice(-1);
    if (kind === "/") setFound(next ? keyboard.previewSearch(next) : null);
  };

  return (
    <div className="vim-line-dock" data-vim-ui>
      <form
        className="vim-line"
        onSubmit={(event) => {
          event.preventDefault();
          keyboard.submitLine(kind, value);
        }}
      >
        {completions.length > 0 && (
          <div className="command-menu vim-completions" role="listbox" aria-label="Completions">
            {completions.map((completion, index) => (
              <button
                key={completion.value}
                type="button"
                role="option"
                aria-selected={index === choice}
                className={`command ${index === choice ? "selected" : ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  setValue(completion.value);
                  setTyped(completion.value);
                  setChoice(-1);
                }}
              >
                <span className="command-name">{completion.label}</span>
                {completion.hint && <span className="command-hint">{completion.hint}</span>}
              </button>
            ))}
          </div>
        )}
        <span className="vim-line-prefix" aria-hidden="true">
          {kind}
        </span>
        <input
          autoFocus
          value={value}
          spellCheck={false}
          autoComplete="off"
          aria-label={kind === ":" ? "Command" : "Search"}
          placeholder={kind === ":" ? "help" : "Search this pane"}
          onChange={(event) => change(event.target.value)}
          onBlur={() => keyboard.cancelLine(kind)}
          onKeyDown={(event) => {
            const key = event.key;
            if (key === "Escape" || (event.ctrlKey && (key === "[" || key === "c"))) {
              event.preventDefault();
              return keyboard.cancelLine(kind);
            }
            // Backspace on an empty line leaves it, as in vim
            if (key === "Backspace" && !value) {
              event.preventDefault();
              return keyboard.cancelLine(kind);
            }
            if (key === "Tab" && completions.length) {
              event.preventDefault();
              const next = (choice + (event.shiftKey ? -1 : 1) + completions.length + 1) % (completions.length + 1);
              // One past the last completion comes back to what was typed
              setChoice(next === completions.length ? -1 : next);
              setValue(next === completions.length ? typed : completions[next].value);
              return;
            }
            if (key === "ArrowUp" || key === "ArrowDown") {
              event.preventDefault();
              const past = keyboard.history(kind);
              const steps = Math.min(Math.max(back + (key === "ArrowUp" ? 1 : -1), 0), past.length);
              setBack(steps);
              change(steps ? past[past.length - steps] : "");
            }
          }}
        />
        {kind === "/" && found !== null && <span className="vim-line-count">{found ? `${found} found` : "No match"}</span>}
      </form>
    </div>
  );
}

const ALWAYS: [string[], string][] = [
  [["Esc", "Ctrl-["], "Stop writing and move around (normal mode)"],
  [["Enter"], "Send the message"],
  [["Shift-Enter"], "New line"],
  [["⌘N"], "New chat"],
  [["⌘B"], "Show or hide the chat list"],
  [["⌘,"], "Settings"],
];

const keyLabels = (binding: Binding) => (binding.label ?? displayKeys(binding.keys)).split(/\s{2,}/);

function KeyRow({ keys, help }: { keys: string[]; help: string }) {
  return (
    <div className="vim-help-row">
      <dt>
        {keys.map((key) => (
          <kbd key={key} className="vim-key">
            {key}
          </kbd>
        ))}
      </dt>
      <dd>{help}</dd>
    </div>
  );
}

/** Every key and command, drawn from the keymap, so it can't fall out of date */
function HelpSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const sections = useMemo(() => {
    const grouped = new Map<string, Binding[]>();
    for (const binding of BINDINGS) {
      if (!binding.hidden) grouped.set(binding.section, [...(grouped.get(binding.section) ?? []), binding]);
    }
    return [...grouped];
  }, []);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className="vim-help glass"
      data-vim-ui
      aria-labelledby="vim-help-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="vim-help-panel" data-vim-help-body tabIndex={-1} autoFocus>
        <header className="vim-help-header">
          <h2 id="vim-help-title">Keyboard</h2>
          <span className="vim-help-hint">j k scroll · Esc closes</span>
        </header>
        <p className="vim-help-intro">
          radAgent works like vim. Writing a message is insert mode; Esc switches to normal mode, where the keys below
          move around, and i goes back to writing. Counts work too: 3j, 2gt.
        </p>
        <div className="vim-help-grid">
          <section>
            <h3>Always</h3>
            <dl>
              {ALWAYS.map(([keys, help]) => (
                <KeyRow key={help} keys={keys} help={help} />
              ))}
            </dl>
          </section>
          {sections.map(([section, bindings]) => (
            <section key={section}>
              <h3>{section}</h3>
              <dl>
                {bindings.map((binding) => (
                  <KeyRow key={`${binding.context}:${binding.keys}`} keys={keyLabels(binding)} help={binding.help} />
                ))}
              </dl>
            </section>
          ))}
          <section>
            <h3>Commands</h3>
            <dl>
              {EX_COMMANDS.filter((command) => !command.hidden).map((command) => (
                <KeyRow key={command.names[0]} keys={[`:${command.names[0]}${command.args ? ` ${command.args}` : ""}`]} help={command.help} />
              ))}
              <KeyRow keys={[":{n}"]} help="Go to message n" />
            </dl>
          </section>
        </div>
      </div>
    </dialog>
  );
}

/**
 * Phones and tablets type on an on-screen keyboard, where normal mode would only get in the way. iOS is the
 * platform main.tsx detects; anything else counts when its main input is touch, with no pointer that can hover
 */
const isMobile = () =>
  document.documentElement.dataset.platform === "ios" || window.matchMedia("(hover: none) and (pointer: coarse)").matches;

/** Vim-style keys for the whole app, except on mobile, where it isn't there at all */
export function KeyboardLayer(props: AppApi) {
  // Checked on first render, not at import: main.tsx marks the platform after its imports have run
  const [mobile] = useState(isMobile);
  return mobile ? null : <VimKeys {...props} />;
}

/** Listens for keys and renders the status line and whatever the keys bring up */
function VimKeys(props: AppApi) {
  // The controller reads the app through this, so its listeners always see the latest chats and callbacks
  const app = useRef(props);
  app.current = props;
  const keyboard = useMemo(() => createKeyboard(() => app.current), []);
  const state = useSyncExternalStore(keyboard.subscribe, keyboard.get);

  useEffect(() => keyboard.attach(), [keyboard]);
  useEffect(() => keyboard.chatOpened(props.activeId), [keyboard, props.activeId]);

  return (
    <>
      <StatusLine state={state} />
      {state.whichKey && state.whichKey.bindings.length > 0 && (
        <WhichKey typed={state.whichKey.typed} bindings={state.whichKey.bindings} pending={state.pending} />
      )}
      {state.hints && <HintLayer hints={state.hints} />}
      {state.line && <CommandLine kind={state.line} keyboard={keyboard} />}
      <HelpSheet open={state.help} onClose={keyboard.closeHelp} />
    </>
  );
}
