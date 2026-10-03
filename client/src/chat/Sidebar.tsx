import { useEffect, useRef, useState } from "react";
import type { ChatSummary } from "../agent";

type Props = {
  open: boolean;
  chats: ChatSummary[];
  activeId: string;
  /** Chats with a reply still coming in */
  answering: Set<string>;
  onToggle: () => void;
  onNew: () => void;
  onOpen: (chat: string) => void;
  onDelete: (chat: string) => void;
};

function ChatRow({
  chat,
  active,
  answering,
  onOpen,
  onDelete,
}: {
  chat: ChatSummary;
  active: boolean;
  answering: boolean;
  onOpen: (chat: string) => void;
  onDelete: (chat: string) => void;
}) {
  // Deleting also deletes what the agent remembers from the chat, so it takes a second click
  const [confirming, setConfirming] = useState(false);
  const remove = useRef<HTMLButtonElement>(null);

  // A touch never leaves the row and a tap doesn't focus the button, so pressing anywhere else calls it off too
  useEffect(() => {
    if (!confirming) return;
    const cancel = (event: PointerEvent) => {
      if (!remove.current?.contains(event.target as Node)) setConfirming(false);
    };
    document.addEventListener("pointerdown", cancel, true);
    return () => document.removeEventListener("pointerdown", cancel, true);
  }, [confirming]);

  return (
    <div className={`chat-row ${active ? "active" : ""}`} onMouseLeave={() => setConfirming(false)}>
      <button
        type="button"
        className="chat-open"
        title={chat.title}
        aria-current={active ? "page" : undefined}
        onClick={() => onOpen(chat.id)}
      >
        <span className="chat-title">{chat.title}</span>
        {answering && <span className="chat-live" role="status" aria-label="Answering" />}
      </button>
      <button
        ref={remove}
        type="button"
        className={`chat-delete ${confirming ? "confirming" : ""}`}
        aria-label={confirming ? `Confirm deleting “${chat.title}”` : `Delete “${chat.title}”`}
        onClick={() => (confirming ? onDelete(chat.id) : setConfirming(true))}
        onBlur={() => setConfirming(false)}
      >
        {confirming ? (
          "Delete"
        ) : (
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4.75 4.75l6.5 6.5M11.25 4.75l-6.5 6.5" />
          </svg>
        )}
      </button>
    </div>
  );
}

/** The chat list, sliding in from the left; its two buttons stay put beside the window controls when it's hidden */
export function Sidebar({ open, chats, activeId, answering, onToggle, onNew, onOpen, onDelete }: Props) {
  return (
    <>
      <div className="sidebar-tools">
        <button
          type="button"
          className="icon-button"
          onClick={onToggle}
          aria-label={open ? "Hide chats" : "Show chats"}
          aria-expanded={open}
          title={`${open ? "Hide" : "Show"} chats (⌘B)`}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <rect x="2" y="3" width="12" height="10" rx="2.5" />
            <path d="M6.25 3v10" />
          </svg>
        </button>
        <button type="button" className="icon-button" onClick={onNew} aria-label="New chat" title="New chat (⌘N)">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M13.25 8.75v2.5a2 2 0 0 1-2 2h-6.5a2 2 0 0 1-2-2v-6.5a2 2 0 0 1 2-2h2.5" />
            <path d="M11.4 2.6a1.35 1.35 0 0 1 1.9 1.9L8.6 9.2l-2.35.55.55-2.35z" />
          </svg>
        </button>
      </div>

      {/* Only drawn on a narrow touchscreen (App.css), where the open list covers the chat: a tap beside it closes it */}
      <div className="sidebar-scrim" aria-hidden="true" onClick={onToggle} />

      <aside className="sidebar" aria-label="Chats" inert={!open}>
        <div className="sidebar-head" data-tauri-drag-region />
        <nav className="chat-list">
          {chats.length === 0 ? (
            <p className="chat-empty">Your chats will show up here</p>
          ) : (
            chats.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                active={chat.id === activeId}
                answering={answering.has(chat.id)}
                onOpen={onOpen}
                onDelete={onDelete}
              />
            ))
          )}
        </nav>
      </aside>
    </>
  );
}
