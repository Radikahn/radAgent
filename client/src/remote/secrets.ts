import { invoke, isTauri } from "@tauri-apps/api/core";

/**
 * Small secrets the app keeps between launches (the Cognito refresh token): in the Keychain on macOS and iOS, through
 * the `secret_*` commands in src-tauri/src/lib.rs. A plain browser (the web preview) has no Keychain, so there they
 * last only for the tab's session
 */
export async function getSecret(name: string): Promise<string | null> {
  if (isTauri()) return invoke<string | null>("secret_get", { name });
  return sessionStorage.getItem(`radagent.${name}`);
}

export async function setSecret(name: string, value: string): Promise<void> {
  if (isTauri()) return invoke("secret_set", { name, value });
  sessionStorage.setItem(`radagent.${name}`, value);
}

export async function deleteSecret(name: string): Promise<void> {
  if (isTauri()) return invoke("secret_delete", { name });
  sessionStorage.removeItem(`radagent.${name}`);
}
