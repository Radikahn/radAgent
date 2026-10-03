import { cognitoClientId, region, remote } from "./config";
import { deleteSecret, getSecret, setSecret } from "./secrets";

/**
 * Signing in to the Cognito user pool in infra/auth.tf, straight against its API (no SDK). The access token goes to
 * AgentCore with every connection; the refresh token stays in the Keychain so the app stays signed in for its 90 days
 */
const REFRESH_TOKEN = "cognito-refresh-token";
// Refresh this long before the access token runs out, so a connection never starts with one about to expire
const EXPIRY_MARGIN_MS = 5 * 60 * 1000;

type Tokens = { accessToken: string; expiresAt: number };

let tokens: Tokens | null = null;
const listeners = new Set<(signedIn: boolean) => void>();

export class AuthError extends Error {
  constructor(
    message: string,
    /** Cognito's error type, e.g. NotAuthorizedException */
    readonly type: string = "",
  ) {
    super(message);
  }
}

/** A step sign-in still needs from the user */
export type Challenge = { kind: "mfa"; session: string; email: string };

async function cognito(action: string, body: object): Promise<any> {
  const response = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const type = String(data.__type ?? "").split("#").pop() ?? "";
    throw new AuthError(data.message ?? `Sign-in failed (${response.status})`, type);
  }
  return data;
}

async function accept(result: any): Promise<void> {
  tokens = { accessToken: result.AccessToken, expiresAt: Date.now() + result.ExpiresIn * 1000 };
  // A refresh doesn't hand back a new refresh token; the one from signing in keeps working
  if (result.RefreshToken) await setSecret(REFRESH_TOKEN, result.RefreshToken);
  listeners.forEach((listener) => listener(true));
}

/** Sign in with email and password; resolves to a challenge when the account has an authenticator app set up */
export async function signIn(email: string, password: string): Promise<Challenge | null> {
  const data = await cognito("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: cognitoClientId,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  if (data.ChallengeName === "SOFTWARE_TOKEN_MFA") return { kind: "mfa", session: data.Session, email };
  if (data.ChallengeName) {
    throw new AuthError(`This account needs ${data.ChallengeName}; finish setting it up with scripts/create-user.sh`);
  }
  await accept(data.AuthenticationResult);
  return null;
}

/** Finish signing in with the six-digit code from the authenticator app */
export async function answerChallenge(challenge: Challenge, code: string): Promise<void> {
  const data = await cognito("RespondToAuthChallenge", {
    ChallengeName: "SOFTWARE_TOKEN_MFA",
    ClientId: cognitoClientId,
    Session: challenge.session,
    ChallengeResponses: { USERNAME: challenge.email, SOFTWARE_TOKEN_MFA_CODE: code },
  });
  await accept(data.AuthenticationResult);
}

/**
 * A current access token, refreshed when it's close to expiring; null when signed out. Running locally there is no
 * sign-in, so this is always "" there
 */
export async function accessToken(options: { force?: boolean } = {}): Promise<string | null> {
  if (!remote) return "";
  if (tokens && !options.force && tokens.expiresAt - Date.now() > EXPIRY_MARGIN_MS) return tokens.accessToken;
  const refreshToken = await getSecret(REFRESH_TOKEN);
  if (!refreshToken) return null;
  try {
    const data = await cognito("InitiateAuth", {
      AuthFlow: "REFRESH_TOKEN_AUTH",
      ClientId: cognitoClientId,
      AuthParameters: { REFRESH_TOKEN: refreshToken },
    });
    await accept(data.AuthenticationResult);
    return tokens!.accessToken;
  } catch (error) {
    // A revoked or expired refresh token means signing in again; anything else (offline) is worth retrying later
    if (error instanceof AuthError && error.type === "NotAuthorizedException") {
      await forget();
      return null;
    }
    throw error;
  }
}

async function forget(): Promise<void> {
  tokens = null;
  await deleteSecret(REFRESH_TOKEN);
  listeners.forEach((listener) => listener(false));
}

/** Sign out on this device; the refresh token is revoked so it can't be used again */
export async function signOut(): Promise<void> {
  const refreshToken = await getSecret(REFRESH_TOKEN);
  if (refreshToken) {
    await cognito("RevokeToken", { Token: refreshToken, ClientId: cognitoClientId }).catch(() => {});
  }
  await forget();
}

/** Call `listener` whenever this device signs in or out */
export function onAuthChange(listener: (signedIn: boolean) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The claims in a JWT's payload; the token's signature is AgentCore's to check, not ours */
export function claims(token: string): Record<string, unknown> {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), "=")));
  } catch {
    return {};
  }
}
