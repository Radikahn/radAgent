import { choice, type Setting } from "./schema";

/**
 * Every setting the app has. Adding one is adding an entry here: the modal draws a row for it, the store persists
 * it, and `apply` puts it into effect. The key is how code reads it (`settings.get().theme`) and is what's stored,
 * so renaming one resets it to its default.
 */
export const definitions = {
  theme: choice({
    section: "Appearance",
    label: "Theme",
    options: [
      { value: "system", label: "System" },
      { value: "light", label: "Light" },
      { value: "dark", label: "Dark" },
    ],
    default: "system",
    apply(theme) {
      // App.css flips color-scheme on this; without it the system's light or dark is used
      if (theme === "system") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = theme;
    },
  }),
} satisfies Record<string, Setting>;
