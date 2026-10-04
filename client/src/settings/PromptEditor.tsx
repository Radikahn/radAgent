import { useEffect, useRef, useState } from "react";
import { prompts, slotLabel, usePrompts, type PromptSlot } from "./prompts";

// The agent's limits (agent/src/radagent/prompts/presets.py)
const NAME_CHARS = 40;
const PROMPT_CHARS = 100_000;

/** Whether two versions of a slot save the same; the agent collapses spaces in names and trims prompts */
const name = (slot: PromptSlot | undefined) => (slot?.name ?? "").split(/\s+/).filter(Boolean).join(" ");
const same = (a: PromptSlot | undefined, b: PromptSlot | undefined) =>
  name(a) === name(b) && (a?.text ?? "").trim() === (b?.text ?? "").trim();

/**
 * The custom prompt menu: the three presets as tabs, each with a name and its prompt to edit. It stays mounted
 * while closed, so unsaved edits are still there when it opens again
 */
export function PromptEditor({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { presets, error, saving } = usePrompts();
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState(0);
  // Edits not yet saved, by slot; a slot without one shows what's saved
  const [drafts, setDrafts] = useState<Record<number, PromptSlot>>({});

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  // Opening on the prompt in use is what most edits are for
  useEffect(() => {
    if (open && presets) setSelected(presets.active);
    // Only as it opens; a change made meanwhile on another device shouldn't move the tab under the user
  }, [open]);

  // A draft that now matches what's saved (it was just saved, here or on another device) is no longer a draft
  useEffect(() => {
    if (!presets) return;
    setDrafts((current) => {
      const kept = Object.entries(current).filter(([slot, draft]) => !same(draft, presets.slots[Number(slot)]));
      return kept.length === Object.keys(current).length ? current : Object.fromEntries(kept);
    });
  }, [presets]);

  const saved = presets?.slots[selected];
  const value = drafts[selected] ?? saved ?? { name: "", text: "" };
  const dirty = drafts[selected] !== undefined && !same(drafts[selected], saved);
  const inUse = presets?.active === selected;
  const empty = !value.text.trim();

  const edit = (change: Partial<PromptSlot>) => setDrafts({ ...drafts, [selected]: { ...value, ...change } });
  const save = () => prompts.save(selected, value.name, value.text);

  return (
    <dialog
      ref={dialog}
      className="settings prompt-editor glass"
      aria-labelledby="prompt-editor-title"
      onClose={onClose}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "s" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          if (dirty && !(inUse && empty)) save();
        }
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="settings-panel prompt-panel">
        <header className="settings-header">
          <h2 id="prompt-editor-title">Prompts</h2>
          <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4.75 4.75l6.5 6.5M11.25 4.75l-6.5 6.5" />
            </svg>
          </button>
        </header>
        <p className="setting-description prompt-intro">
          The agent's system prompt, in three presets every device shares. The tool list is added to the end of it.
        </p>

        {!presets ? (
          <p className="prompt-status">{error ?? "Loading the prompts…"}</p>
        ) : (
          <>
            <div className="prompt-tabs" role="tablist" aria-label="Presets">
              {presets.slots.map((slot, index) => {
                const draft = drafts[index];
                return (
                  <button
                    key={index}
                    type="button"
                    role="tab"
                    id={`prompt-tab-${index}`}
                    aria-selected={index === selected}
                    aria-controls="prompt-slot"
                    className={[index === selected && "selected", index === presets.active && "in-use"].filter(Boolean).join(" ")}
                    onClick={() => setSelected(index)}
                  >
                    <span className="prompt-tab-number">{index + 1}</span>
                    <span className="prompt-tab-name">{slotLabel(draft ?? slot, index)}</span>
                    {draft && !same(draft, slot) && <span className="prompt-tab-dot" aria-label="unsaved" />}
                    {index === presets.active && <span className="prompt-tab-active">In use</span>}
                  </button>
                );
              })}
            </div>

            <div className="prompt-slot" id="prompt-slot" role="tabpanel" aria-labelledby={`prompt-tab-${selected}`}>
              <input
                className="prompt-name"
                type="text"
                placeholder={`Prompt ${selected + 1}`}
                aria-label="Name"
                maxLength={NAME_CHARS}
                value={value.name}
                onChange={(event) => edit({ name: event.target.value })}
              />
              <textarea
                className="prompt-text"
                placeholder="You are…"
                aria-label="Prompt"
                spellCheck={false}
                maxLength={PROMPT_CHARS}
                value={value.text}
                onChange={(event) => edit({ text: event.target.value })}
              />
            </div>

            <footer className="prompt-footer">
              <span className="prompt-status" role="status">
                {error ??
                  (saving
                    ? "Saving…"
                    : inUse && empty
                      ? "The prompt in use can't be empty"
                      : `${value.text.length.toLocaleString()} characters${dirty ? " · unsaved" : ""}`)}
              </span>
              <div className="prompt-actions">
                {dirty && (
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => {
                      const { [selected]: _reverted, ...rest } = drafts;
                      setDrafts(rest);
                    }}
                  >
                    Revert
                  </button>
                )}
                {!inUse && (
                  <button
                    type="button"
                    className="pill"
                    disabled={empty || saving}
                    onClick={() => {
                      if (dirty) save();
                      prompts.use(selected);
                    }}
                  >
                    {dirty ? "Save and use" : "Use"}
                  </button>
                )}
                <button
                  type="button"
                  className="pill primary"
                  disabled={!dirty || saving || (inUse && empty)}
                  onClick={save}
                >
                  {!dirty || !empty ? "Save" : "Clear"}
                </button>
              </div>
            </footer>
          </>
        )}
      </div>
    </dialog>
  );
}
