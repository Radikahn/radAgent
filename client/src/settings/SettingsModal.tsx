import { useEffect, useRef, useState, type ComponentType } from "react";
import { signOut } from "../remote/auth";
import { remote } from "../remote/config";
import { googleConfigured } from "../remote/google";
import { GoogleSection } from "./GoogleSection";
import { PromptEditor } from "./PromptEditor";
import { prompts, slotLabel, usePrompts } from "./prompts";
import type { ChoiceSetting, Setting, ToggleSetting, ValueOf } from "./schema";
import { settings, type SettingKey } from "./store";
import { useSettings } from "./useSettings";
import "./settings.css";

type ControlProps<S extends Setting> = {
  /** Unique in the modal; the row's label is `${id}-label` */
  id: string;
  setting: S;
  value: ValueOf<S>;
  onChange: (value: ValueOf<S>) => void;
};

function ChoiceControl({ id, setting, value, onChange }: ControlProps<ChoiceSetting>) {
  return (
    <div className="segmented" role="radiogroup" aria-labelledby={`${id}-label`}>
      {setting.options.map((option) => (
        <label key={option.value}>
          <input type="radio" name={id} checked={value === option.value} onChange={() => onChange(option.value)} />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

function ToggleControl({ id, value, onChange }: ControlProps<ToggleSetting>) {
  return (
    <input
      type="checkbox"
      role="switch"
      className="switch"
      aria-labelledby={`${id}-label`}
      checked={value}
      onChange={(event) => onChange(event.target.checked)}
    />
  );
}

/** How each kind of setting is drawn; leaving a kind out is a type error */
const controls: { [K in Setting["kind"]]: ComponentType<ControlProps<Extract<Setting, { kind: K }>>> } = {
  choice: ChoiceControl,
  toggle: ToggleControl,
};

/** Setting keys under each heading, in definition order */
const sections = new Map<string, SettingKey[]>();
for (const key of Object.keys(settings.definitions) as SettingKey[]) {
  const { section } = settings.definitions[key];
  sections.set(section, [...(sections.get(section) ?? []), key]);
}

/**
 * The agent's prompt presets, one tap to swap between, and the button to the menu that edits them. They live with the
 * agent rather than in definitions.ts, which holds this device's settings
 */
function PromptSetting({ onEdit }: { onEdit: () => void }) {
  const { presets, error } = usePrompts();
  return (
    <div className="setting prompt-setting">
      <div className="prompt-setting-top">
        <div className="setting-text">
          <span id="setting-prompt-label">System prompt</span>
          <span className="setting-description">
            {error ?? (presets ? "Swapping applies to every chat from its next reply" : "Waiting for the agent…")}
          </span>
        </div>
        <button type="button" className="pill" onClick={onEdit}>
          Edit prompts
        </button>
      </div>
      {presets && (
        <div className="segmented prompt-slots" role="radiogroup" aria-labelledby="setting-prompt-label">
          {presets.slots.map((slot, index) => (
            <label key={index} title={slot.text ? undefined : "Empty; write a prompt in it under Edit prompts"}>
              <input
                type="radio"
                name="setting-prompt"
                checked={presets.active === index}
                disabled={!slot.text}
                onChange={() => prompts.use(index)}
              />
              <span>
                <b>{index + 1}</b> {slotLabel(slot, index)}
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/** Draws a row for every setting in definitions.ts, so new settings show up here without touching this file */
function SettingsModal({
  open,
  onClose,
  onEditPrompts,
}: {
  open: boolean;
  onClose: () => void;
  onEditPrompts: () => void;
}) {
  const values = useSettings();
  const dialog = useRef<HTMLDialogElement>(null);

  // A modal <dialog> traps focus, closes on Esc, makes the page behind it inert, and hands focus back after
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className="settings glass"
      aria-labelledby="settings-title"
      onClose={onClose}
      // Keys pressed in here are for the modal, so the app's shortcuts (Esc stopping a reply, ⌘N, ...) don't fire behind it
      onKeyDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        // The panel fills the dialog, so a click landing on the dialog itself was on the backdrop
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="settings-panel">
        <header className="settings-header">
          <h2 id="settings-title">Settings</h2>
          <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4.75 4.75l6.5 6.5M11.25 4.75l-6.5 6.5" />
            </svg>
          </button>
        </header>

        {[...sections].map(([section, keys]) => (
          <section key={section} className="settings-section">
            <h3>{section}</h3>
            {keys.map((key) => {
              const setting: Setting = settings.definitions[key];
              const Control = controls[setting.kind] as ComponentType<ControlProps<Setting>>;
              const id = `setting-${key}`;
              return (
                <div key={key} className="setting">
                  <div className="setting-text">
                    <span id={`${id}-label`}>{setting.label}</span>
                    {setting.description && <span className="setting-description">{setting.description}</span>}
                  </div>
                  <Control
                    id={id}
                    setting={setting}
                    value={values[key]}
                    onChange={(value) => settings.set(key, value as (typeof values)[typeof key])}
                  />
                </div>
              );
            })}
          </section>
        ))}

        <section className="settings-section">
          <h3>Agent</h3>
          <PromptSetting onEdit={onEditPrompts} />
        </section>

        {googleConfigured && <GoogleSection open={open} />}

        {remote && (
          <section className="settings-section">
            <h3>Account</h3>
            <div className="setting">
              <div className="setting-text">
                <span>Signed in to your agent on AWS</span>
                <span className="setting-description">Signing out forgets this device's session</span>
              </div>
              <button
                type="button"
                className="quiet"
                onClick={() => {
                  onClose();
                  void signOut();
                }}
              >
                Sign out
              </button>
            </div>
          </section>
        )}
      </div>
    </dialog>
  );
}

/** The gear in the window's bottom-left corner and the modal it opens; ⌘, opens it too */
export function Settings() {
  const [open, setOpen] = useState(false);
  const [editingPrompts, setEditingPrompts] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "," && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <button
        type="button"
        className="settings-button icon-button"
        aria-label="Settings"
        title="Settings (⌘,)"
        onClick={() => setOpen(true)}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6.68 3.07L6.92 1.18A6.9 6.9 0 0 1 9.08 1.18L9.32 3.07A5.1 5.1 0 0 1 10.55 3.58L12.06 2.42A6.9 6.9 0 0 1 13.58 3.94L12.42 5.45A5.1 5.1 0 0 1 12.93 6.68L14.82 6.92A6.9 6.9 0 0 1 14.82 9.08L12.93 9.32A5.1 5.1 0 0 1 12.42 10.55L13.58 12.06A6.9 6.9 0 0 1 12.06 13.58L10.55 12.42A5.1 5.1 0 0 1 9.32 12.93L9.08 14.82A6.9 6.9 0 0 1 6.92 14.82L6.68 12.93A5.1 5.1 0 0 1 5.45 12.42L3.94 13.58A6.9 6.9 0 0 1 2.42 12.06L3.58 10.55A5.1 5.1 0 0 1 3.07 9.32L1.18 9.08A6.9 6.9 0 0 1 1.18 6.92L3.07 6.68A5.1 5.1 0 0 1 3.58 5.45L2.42 3.94A6.9 6.9 0 0 1 3.94 2.42L5.45 3.58A5.1 5.1 0 0 1 6.68 3.07Z" />
          <circle cx="8" cy="8" r="2.1" />
        </svg>
      </button>
      <SettingsModal open={open} onClose={() => setOpen(false)} onEditPrompts={() => setEditingPrompts(true)} />
      {/* Beside the settings rather than inside them, so its events don't reach the settings dialog's handlers; it
          opens over them, and closing it goes back to them */}
      <PromptEditor open={editingPrompts} onClose={() => setEditingPrompts(false)} />
    </>
  );
}
