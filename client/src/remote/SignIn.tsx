import { useState, type FormEvent } from "react";
import { answerChallenge, AuthError, signIn, type Challenge } from "./auth";
import "./signin.css";

/** Shown instead of the app until this device has signed in to the agent on AWS; the session then lasts 90 days */
export function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setWorking(true);
    setError("");
    try {
      // Signing in tells the connection, which connects and replaces this screen with the app
      if (challenge) await answerChallenge(challenge, code.trim());
      else setChallenge(await signIn(email.trim(), password));
    } catch (failure) {
      setError(failure instanceof AuthError ? failure.message : `Couldn't reach sign-in: ${String(failure)}`);
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="signin">
      <div className="drag-region" data-tauri-drag-region />
      <form className="signin-panel glass" onSubmit={submit}>
        <h1>radAgent</h1>
        {challenge ? (
          <label>
            <span>Code from your authenticator app</span>
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              autoFocus
              required
            />
          </label>
        ) : (
          <>
            <label>
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                autoFocus
                required
              />
            </label>
            <label>
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
          </>
        )}
        {error && <p className="signin-error">{error}</p>}
        <button type="submit" disabled={working}>
          {working ? "Signing in…" : challenge ? "Verify" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
