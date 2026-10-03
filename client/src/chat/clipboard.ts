/**
 * Puts `text` on the system clipboard. Where the webview has no Clipboard API, or refuses it, the old copy command
 * does it from a hidden text box instead; both only work while handling a click or key press
 */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    if (!copyWithCommand(text)) throw new Error("The clipboard isn't available");
  }
}

function copyWithCommand(text: string): boolean {
  const previous = document.activeElement;
  const box = document.createElement("textarea");
  box.value = text;
  // Read-only so a phone doesn't bring its keyboard up for it
  box.readOnly = true;
  box.style.cssText = "position: fixed; top: 0; left: 0; opacity: 0; pointer-events: none";
  document.body.append(box);
  box.select();
  box.setSelectionRange(0, text.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    // Some engines throw rather than return false
  }
  box.remove();
  // Selecting moved focus, which the keyboard layer follows; give it back
  if (previous instanceof HTMLElement) previous.focus({ preventScroll: true });
  return copied;
}
