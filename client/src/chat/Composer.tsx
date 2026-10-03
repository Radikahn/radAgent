import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { AgentStatus } from "../agent";
import { Attachments } from "./Attachments";
import { parseCommand, suggestCommands, type Command } from "./commands";
import type { PendingFile } from "./files";
import { useAttachments } from "./useAttachments";

type Props = {
  status: AgentStatus;
  busy: boolean;
  /** The chat's history is still loading */
  loading: boolean;
  /** The chat on screen; the input takes focus whenever it changes */
  chatId: string;
  onSend: (text: string, command?: string, files?: PendingFile[]) => void;
  onStop: () => void;
};

/** What a slash command does, or the commands that match while one is being typed */
function CommandMenu({ suggestions, active, onPick }: { suggestions: Command[]; active?: Command; onPick: (command: Command) => void }) {
  if (suggestions.length) {
    return (
      <div className="command-menu materialize" role="listbox" aria-label="Commands">
        {suggestions.map((command, index) => (
          <button
            key={command.name}
            type="button"
            role="option"
            aria-selected={index === 0}
            className={`command ${index === 0 ? "selected" : ""}`}
            // Keep focus in the input so typing carries on after picking
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(command)}
          >
            <span className="command-name">/{command.name}</span>
            <span className="command-hint">{command.hint}</span>
          </button>
        ))}
      </div>
    );
  }
  if (!active) return null;
  return (
    <p className="command-menu command-active materialize">
      <span className="command-name">/{active.name}</span>
      <span className="command-hint">{active.hint}</span>
    </p>
  );
}

// A touchscreen keyboard has no Shift+Enter, so there Return adds a line and only the button (or ⌘/Ctrl+Enter) sends
const touch = window.matchMedia("(pointer: coarse)");

/**
 * The floating glass input: Enter sends, Shift+Enter adds a line (Return alone does on a touchscreen), and the
 * button turns into stop while answering.
 * Files come in through the attach button, by pasting, or by dropping them anywhere on the window
 */
export function Composer({ status, busy, loading, chatId, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const attach = useAttachments();
  const message = parseCommand(text);
  const suggestions = suggestCommands(text);
  const canSend = (message.text !== "" || attach.files.length > 0) && !busy && !loading && status !== "stopped";
  const returnSends = !touch.matches;

  // Not on a touchscreen, where taking focus would bring the keyboard up over the chat just opened
  useEffect(() => {
    if (!touch.matches) input.current?.focus();
  }, [chatId]);

  // Grow with the text; CSS caps the height and scrolls past that
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [text]);

  function submit() {
    if (!canSend) return;
    onSend(message.text, message.command?.name, attach.take());
    setText("");
  }

  function pick(command: Command) {
    setText(`/${command.name} `);
  }

  return (
    <>
      {/* Outside the form: its backdrop filter would otherwise confine the fixed overlay to the input */}
      {attach.dragging && <div className="drop-zone">Drop files to attach</div>}
      <form
        className="composer glass"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <CommandMenu suggestions={suggestions} active={message.command} onPick={pick} />
        {attach.files.length > 0 && <Attachments className="composer-tray" files={attach.files} onRemove={attach.remove} />}
        {attach.problem && (
          <p className="composer-problem" role="alert">
            {attach.problem}
          </p>
        )}
        <button
          type="button"
          className="composer-attach"
          onClick={() => picker.current?.click()}
          // Keep focus in the input so typing carries on after picking
          onMouseDown={(event) => event.preventDefault()}
          aria-label="Attach files"
          title="Attach images, PDFs, Office or text files"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M15.5 9.25 10 14.75a3.89 3.89 0 0 1-5.5-5.5l6-6a2.6 2.6 0 0 1 3.67 3.67l-6 6a1.3 1.3 0 0 1-1.84-1.84l5.5-5.5" />
          </svg>
        </button>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            attach.add(Array.from(event.target.files ?? []));
            // Cleared so picking the same file again still counts as a change
            event.target.value = "";
          }}
        />
        <textarea
          ref={input}
          rows={1}
          autoFocus={returnSends}
          value={text}
          placeholder={status === "starting" ? "Waking up…" : "Ask anything"}
          aria-label="Message"
          enterKeyHint={returnSends ? "send" : "enter"}
          onChange={(event) => setText(event.target.value)}
          onPaste={attach.onPaste}
          onKeyDown={(event) => {
            // While a command's name is being typed, Tab or Enter completes it
            if (suggestions.length && (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey))) {
              event.preventDefault();
              pick(suggestions[0]);
              return;
            }
            const sends = returnSends || event.metaKey || event.ctrlKey;
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && sends) {
              event.preventDefault();
              submit();
            }
          }}
        />
        {busy ? (
          <button
            type="button"
            className="composer-button"
            onClick={onStop}
            // Keep focus in the input so typing carries on after stopping
            onMouseDown={(event) => event.preventDefault()}
            aria-label="Stop"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <rect x="4" y="4" width="8" height="8" rx="1.5" />
            </svg>
          </button>
        ) : (
          <button
            type="submit"
            className="composer-button"
            disabled={!canSend}
            // Keep focus in the input, so a touchscreen's keyboard stays up after sending
            onMouseDown={(event) => event.preventDefault()}
            aria-label="Send"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 13V3.5M3.75 7.5 8 3.25l4.25 4.25" />
            </svg>
          </button>
        )}
      </form>
    </>
  );
}
