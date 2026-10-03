import { useEffect, useState, useSyncExternalStore, type FormEvent } from "react";
import {
  cancelGoogle,
  connectGoogle,
  disconnectGoogle,
  finishGoogle,
  googleState,
  onGoogleChange,
  refreshGoogle,
} from "../remote/google";

// How the consent page names what each scope allows, for a login that's missing some
const SCOPE_NAMES: Record<string, string> = {
  "https://www.googleapis.com/auth/drive": "Drive",
  "https://www.googleapis.com/auth/documents": "Docs",
  "https://www.googleapis.com/auth/calendar": "Calendar",
};

/** Connect Google in Settings: lets the agent use the user's Drive, Docs and Calendar; see remote/google.ts */
export function GoogleSection({ open }: { open: boolean }) {
  const { status, step, problem } = useSyncExternalStore(onGoogleChange, googleState);
  const [address, setAddress] = useState("");

  // Another device may have connected or disconnected since the modal was last open
  useEffect(() => {
    if (open) refreshGoogle();
  }, [open]);

  const paste = (event: FormEvent) => {
    event.preventDefault();
    if (finishGoogle(address)) setAddress("");
  };

  const missing = (status?.missing ?? []).map((scope) => SCOPE_NAMES[scope] ?? scope);
  let label = "Google";
  let description = "Let the agent use your Drive, Docs and Calendar";
  if (step === "waiting") description = "Finish in the browser; it brings you back here";
  else if (step === "connecting") description = "Connecting…";
  else if (status === null) description = "Checking…";
  else if (status.connected) {
    label = status.email ? `Google: ${status.email}` : "Google is connected";
    description = missing.length
      ? `Not allowed: ${missing.join(", ")}. Connect again and tick every box`
      : "The agent can use your Drive, Docs and Calendar";
  }

  return (
    <section className="settings-section">
      <h3>Connections</h3>
      <div className="setting">
        <div className="setting-text">
          <span>{label}</span>
          <span className="setting-description">{description}</span>
          {problem && <span className="setting-description setting-error">{problem}</span>}
        </div>
        <div className="setting-actions">
          {step === "waiting" ? (
            <button type="button" className="quiet" onClick={cancelGoogle}>
              Cancel
            </button>
          ) : status?.connected ? (
            <>
              {missing.length > 0 && (
                <button type="button" className="quiet" onClick={() => void connectGoogle()}>
                  Connect again
                </button>
              )}
              <button type="button" className="quiet" onClick={disconnectGoogle}>
                Disconnect
              </button>
            </>
          ) : (
            <button type="button" className="quiet" disabled={step === "connecting"} onClick={() => void connectGoogle()}>
              Connect
            </button>
          )}
        </div>
      </div>
      {step === "waiting" && (
        <form className="setting setting-paste" onSubmit={paste}>
          <label className="setting-text">
            <span className="setting-description">
              If the app doesn't open by itself, paste the address the browser ended on
            </span>
            <input
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="com.googleusercontent.apps…"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
            />
          </label>
          <button type="submit" className="quiet" disabled={!address.trim()}>
            Done
          </button>
        </form>
      )}
    </section>
  );
}
