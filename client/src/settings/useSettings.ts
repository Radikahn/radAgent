import { useSyncExternalStore } from "react";
import { settings } from "./store";

/** The React binding for the settings store: current values, re-rendering when any changes */
export function useSettings() {
  return useSyncExternalStore(settings.subscribe, settings.get);
}
