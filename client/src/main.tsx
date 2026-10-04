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
 * The iOS app reports that itself (src-tauri/src/keyboard.rs), with how long the keyboard takes to slide, so the dock
 * rides up with it over a page that stays put. Elsewhere the keyboard shrinks the visual viewport but not the layout
 * one that fixed elements follow; on desktop the two match, so it stays 0
 */
function trackKeyboard() {
  const root = document.documentElement;
  let inset = 0;
  const set = (covered: number, seconds: number) => {
    const next = Math.max(0, Math.round(covered));
    if (next === inset) return;
    // Before the inset, so its transition (App.css) eases this way and takes this long
    root.dataset.keyboard = next > inset ? "rising" : "falling";
    root.style.setProperty("--keyboard-duration", `${seconds}s`);
    root.style.setProperty("--keyboard-inset", `${next}px`);
    inset = next;
  };

  const viewport = window.visualViewport;
  const update = () => {
    if (!viewport) return;
    // Pinch-zoom shrinks the visual viewport as well, and that's no keyboard
    set(viewport.scale > 1 ? 0 : window.innerHeight - viewport.height - viewport.offsetTop, 0);
  };
  viewport?.addEventListener("resize", update);
  viewport?.addEventListener("scroll", update);
  update();

  window.addEventListener("native-keyboard", (event) => {
    viewport?.removeEventListener("resize", update);
    viewport?.removeEventListener("scroll", update);
    const { height, duration } = (event as CustomEvent<{ height: number; duration: number }>).detail;
    set(height, duration);
  });
}

/**
 * A tap anywhere but a field or the composer puts the keyboard away; iOS shows no button for it (keyboard.rs).
 * A drag that scrolls the chat ends in pointercancel rather than pointerup, so scrolling leaves the keyboard up
 */
function dismissKeyboardOnTap() {
  document.addEventListener("pointerup", (event) => {
    const field = document.activeElement;
    if (event.pointerType !== "touch" || !(field instanceof HTMLElement)) return;
    if (!field.matches("input, textarea, [contenteditable]")) return;
    const target = event.target as Element;
    if (target.closest(".composer, input, textarea, select, label, [contenteditable]")) return;
    field.blur();
  });
}

document.documentElement.dataset.platform = detectPlatform();
trackKeyboard();
dismissKeyboardOnTap();
// Google's consent page can send the browser back to the app at any moment, Settings open or not
listenForGoogle();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
