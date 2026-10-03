import { useEffect, useRef, useState } from "react";
import { useAgent } from "./agent";
import { Composer } from "./chat/Composer";
import { Sidebar } from "./chat/Sidebar";
import { TurnView } from "./chat/TurnView";
import { KeyboardLayer } from "./keys/KeyboardLayer";
import { SignIn } from "./remote/SignIn";
import { Settings } from "./settings/SettingsModal";
import "./App.css";

const SIDEBAR_KEY = "radagent.sidebar";
// Below this width the sidebar covers the chat instead of pushing it aside; keep in step with App.css
const NARROW = "(max-width: 720px)";

const isNarrow = () => window.matchMedia(NARROW).matches;

/**
 * Whether the sidebar is open. Showing or hiding it is remembered across launches; narrow windows start with it
 * closed and close it after a chat is picked, without forgetting what the user chose
 */
function useSidebar() {
  const [open, setOpen] = useState(() => {
    if (isNarrow()) return false;
    try {
      return localStorage.getItem(SIDEBAR_KEY) !== "closed";
    } catch {
      return true;
    }
  });
  const toggle = () => {
    try {
      localStorage.setItem(SIDEBAR_KEY, open ? "closed" : "open");
    } catch {
      // Storage can be unavailable; the sidebar just won't remember
    }
    setOpen(!open);
  };
  const closeIfNarrow = () => {
    if (isNarrow()) setOpen(false);
  };
  return { open, toggle, closeIfNarrow };
}

/** Keeps the newest text in view while it streams, until the user scrolls up to read something earlier */
function useFollowBottom() {
  const scroller = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => {
    const scrollElement = scroller.current;
    const contentElement = content.current;
    if (!scrollElement || !contentElement) return;

    const onScroll = () => {
      const fromBottom = scrollElement.scrollHeight - scrollElement.scrollTop - scrollElement.clientHeight;
      following.current = fromBottom < 64;
    };
    const observer = new ResizeObserver(() => {
      if (following.current) scrollElement.scrollTop = scrollElement.scrollHeight;
    });
    scrollElement.addEventListener("scroll", onScroll, { passive: true });
    observer.observe(contentElement);
    return () => {
      scrollElement.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, []);

  const follow = () => {
    following.current = true;
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  };

  /** Straight to the end, e.g. on opening another chat */
  const jump = () => {
    following.current = true;
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  };

  return { scroller, content, follow, jump };
}

/** Publishes the dock's height so the thread can always scroll its last line clear of the input */
function useDockHeight() {
  const dock = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = dock.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      document.documentElement.style.setProperty("--dock-height", `${element.offsetHeight}px`),
    );
    // The border box, since the gap under the input (padding) changes as the on-screen keyboard comes and goes
    observer.observe(element, { box: "border-box" });
    return () => observer.disconnect();
  }, []);
  return dock;
}

export default function App() {
  const agent = useAgent();
  // The agent on AWS needs this device signed in first; a local agent never asks
  if (agent.signedOut) return <SignIn />;
  return <Workspace agent={agent} />;
}

/**
 * The chat itself. Its own component so the hooks above attach to the thread and dock it draws: had they lived in
 * App, signing in again would leave them watching the elements from before the sign-in screen
 */
function Workspace({ agent }: { agent: ReturnType<typeof useAgent> }) {
  const { status, chats, activeId, turns, loading, answering, notice, send, stop, restart } = agent;
  const { scroller, content, follow, jump } = useFollowBottom();
  const dock = useDockHeight();
  const sidebar = useSidebar();
  const busy = turns[turns.length - 1]?.status === "streaming";

  useEffect(jump, [activeId]);

  // On a narrow window the sidebar covers the chat, so it gets out of the way once a chat is picked
  const openChat = (chat: string) => {
    agent.openChat(chat);
    sidebar.closeIfNarrow();
  };
  const newChat = () => {
    // A chat with no messages yet is already a new chat
    if (turns.length) agent.newChat();
    sidebar.closeIfNarrow();
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const command = event.metaKey || event.ctrlKey;
      if (event.key === "Escape" && busy) stop();
      // ⌘N / Ctrl+N starts a new chat, with its own context and memory
      if (command && event.key.toLowerCase() === "n") {
        event.preventDefault();
        newChat();
      }
      // ⌘B / Ctrl+B shows or hides the chat list
      if (command && event.key.toLowerCase() === "b") {
        event.preventDefault();
        sidebar.toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className={`app ${sidebar.open ? "sidebar-open" : ""}`}>
      {/* The title bar is hidden, so this invisible strip is where the window is dragged */}
      <div className="drag-region" data-tauri-drag-region />

      <Sidebar
        open={sidebar.open}
        chats={chats}
        activeId={activeId}
        answering={answering}
        onToggle={sidebar.toggle}
        onNew={newChat}
        onOpen={openChat}
        onDelete={agent.deleteChat}
      />

      <main className="thread" ref={scroller}>
        <div className="thread-content" ref={content}>
          {turns.map((turn) => (
            <TurnView key={turn.id} turn={turn} />
          ))}
        </div>
      </main>

      <footer className="dock" ref={dock}>
        {notice && (
          <p className="notice materialize">
            {notice}
            {status === "starting" && (
              <button type="button" className="quiet" onClick={restart}>
                Retry now
              </button>
            )}
          </p>
        )}
        <Composer
          status={status}
          busy={busy}
          loading={loading}
          chatId={activeId}
          onStop={stop}
          onSend={(text, command, files) => {
            follow();
            send(text, command, files);
          }}
        />
      </footer>

      <Settings />

      {/* Vim-style keys for everything above: see client/src/keys, or press ? in the app */}
      <KeyboardLayer
        chats={chats}
        activeId={activeId}
        turns={turns}
        busy={busy}
        answering={answering}
        sidebarOpen={sidebar.open}
        toggleSidebar={sidebar.toggle}
        openChat={openChat}
        newChat={newChat}
        deleteChat={agent.deleteChat}
        stop={stop}
        restart={restart}
      />
    </div>
  );
}
