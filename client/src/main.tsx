import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { listenForGoogle } from "./remote/google";

/**
 * Which platform the window is on, for the CSS that differs (App.css): macOS keeps its window controls in the top
 * corner, iOS has the notch and the home indicator. iPadOS says it's a Mac, so touch points tell them apart
 */
function detectPlatform(): "macos" | "ios" | "other" {
  const agent = navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(agent) || (/Macintosh/.test(agent) && navigator.maxTouchPoints > 1)) return "ios";
  if (/Macintosh/.test(agent) && navigator.maxTouchPoints < 2) return "macos";
  return "other";
}

/**
 * Keeps --keyboard-inset at how much of the window the on-screen keyboard covers, so the dock can sit above it.
 * The keyboard shrinks the visual viewport but not the layout one that fixed elements follow; on desktop the two
 * match, so it stays 0
 */
function trackKeyboard() {
  const viewport = window.visualViewport;
  if (!viewport) return;
  let inset = 0;
  const update = () => {
    // Pinch-zoom shrinks the visual viewport as well, and that's no keyboard
    const covered = viewport.scale > 1 ? 0 : window.innerHeight - viewport.height - viewport.offsetTop;
    const next = Math.max(0, Math.round(covered));
    if (next === inset) return;
    inset = next;
    document.documentElement.style.setProperty("--keyboard-inset", `${inset}px`);
  };
  viewport.addEventListener("resize", update);
  viewport.addEventListener("scroll", update);
  update();
}

document.documentElement.dataset.platform = detectPlatform();
trackKeyboard();
// Google's consent page can send the browser back to the app at any moment, Settings open or not
listenForGoogle();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
