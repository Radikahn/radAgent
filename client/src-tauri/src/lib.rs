// The webview talks to the agent on AWS over a WebSocket (src/remote/connection.ts), so the app no longer runs it.
// What stays native is the Keychain, which the webview can't reach: it keeps the sign-in's refresh token, so the app
// stays signed in across launches, on macOS and iOS alike.

// Saving exports (a /research report as text) to Downloads; keep `export_save` registered below when changing this file
mod export;

/// Keychain service the app's secrets are filed under
const KEYCHAIN_SERVICE: &str = "com.radman.radagent";

/// The webview names its secrets; keep those names plain so they can't be used to reach other entries
fn entry(name: &str) -> Result<keyring::Entry, String> {
    let valid = !name.is_empty()
        && name.len() <= 64
        && name.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
    if !valid {
        return Err(format!("Not a secret name: {name:?}"));
    }
    keyring::Entry::new(KEYCHAIN_SERVICE, name).map_err(|e| e.to_string())
}

#[tauri::command]
fn secret_get(name: String) -> Result<Option<String>, String> {
    match entry(&name)?.get_password() {
        Ok(secret) => Ok(Some(secret)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
fn secret_set(name: String, value: String) -> Result<(), String> {
    entry(&name)?.set_password(&value).map_err(|e| e.to_string())
}

#[tauri::command]
fn secret_delete(name: String) -> Result<(), String> {
    match entry(&name)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![secret_get, secret_set, secret_delete, export::export_save])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
