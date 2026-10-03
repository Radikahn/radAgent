import { definitions } from "./definitions";
import { isValid, type Setting, type ValueOf } from "./schema";

type Definitions = Record<string, Setting>;
type Values<D extends Definitions> = { [K in keyof D]: ValueOf<D[K]> };

/** Holds the current values, keeps them in localStorage, and tells subscribers when one changes; any UI can sit on top */
export function createSettingsStore<D extends Definitions>(definitions: D, storageKey: string) {
  const keys = Object.keys(definitions) as (keyof D & string)[];
  const listeners = new Set<() => void>();
  let values = load();

  function load(): Values<D> {
    let stored: Record<string, unknown> = {};
    try {
      stored = JSON.parse(localStorage.getItem(storageKey) ?? "{}");
    } catch {
      // Unreadable storage means defaults, not a broken app
    }
    // Anything missing or no longer allowed falls back to its default
    return Object.fromEntries(
      keys.map((key) => [key, isValid(definitions[key], stored[key]) ? stored[key] : definitions[key].default]),
    ) as Values<D>;
  }

  function apply<K extends keyof D>(key: K) {
    (definitions[key] as Setting).apply?.(values[key] as never);
  }

  keys.forEach(apply);

  return {
    definitions,

    /** The same object until something changes, so it can be compared by identity */
    get: (): Values<D> => values,

    set<K extends keyof D & string>(key: K, value: Values<D>[K]) {
      if (!isValid(definitions[key], value) || Object.is(values[key], value)) return;
      values = { ...values, [key]: value };
      try {
        localStorage.setItem(storageKey, JSON.stringify(values));
      } catch {
        // Still applied for this session, just not remembered
      }
      apply(key);
      listeners.forEach((listener) => listener());
    },

    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export type SettingKey = keyof typeof definitions;

export const settings = createSettingsStore(definitions, "radagent.settings");
