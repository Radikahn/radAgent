// The kinds of setting there are; plain TypeScript, so nothing here depends on React or the DOM

type Base<V> = {
  /** Groups rows under a heading in the settings modal; sections show in the order they're first used */
  section: string;
  label: string;
  /** One line under the label */
  description?: string;
  default: V;
  /** Runs at startup and on every change, to push the value to wherever it takes effect (the DOM, the agent, ...) */
  apply?(value: V): void;
};

/** One of a few named values, shown as a segmented control */
export type ChoiceSetting<V extends string = string> = Base<V> & {
  kind: "choice";
  options: readonly { value: V; label: string }[];
};

/** On or off, shown as a switch */
export type ToggleSetting = Base<boolean> & { kind: "toggle" };

/** Adding a kind: add it here, teach `isValid` to check its values, and give it a control in SettingsModal.tsx */
export type Setting = ChoiceSetting | ToggleSetting;

export type ValueOf<S extends Setting> = S extends ChoiceSetting<infer V> ? V : S extends ToggleSetting ? boolean : never;

export const choice = <const V extends string>(setting: Omit<ChoiceSetting<V>, "kind">): ChoiceSetting<V> => ({
  kind: "choice",
  ...setting,
});

export const toggle = (setting: Omit<ToggleSetting, "kind">): ToggleSetting => ({ kind: "toggle", ...setting });

/** Whether a value (e.g. one read back from storage) is still allowed, since options can change between versions */
export function isValid(setting: Setting, value: unknown): boolean {
  switch (setting.kind) {
    case "choice":
      return setting.options.some((option) => option.value === value);
    case "toggle":
      return typeof value === "boolean";
  }
}
