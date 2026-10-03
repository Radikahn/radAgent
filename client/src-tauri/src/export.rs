// Saves exports from the webview, such as a /research report as text (client/src/research/exportReport.ts). A webview
// can't write files, and a browser-style download goes nowhere in a Tauri window, so the app writes them itself.

use std::fs::{self, OpenOptions};
use std::io::{ErrorKind, Write};
use std::path::Path;

use tauri::{AppHandle, Manager};

/// File types the webview may save
const EXTENSIONS: [&str; 2] = ["txt", "md"];
/// Longest name kept, before the extension
const MAX_STEM_CHARS: usize = 120;

/// The name the webview asked for, minus anything that could leave the folder or trip up a file system
fn clean_name(name: &str) -> Option<(String, String)> {
    let path = Path::new(name);
    let extension = path.extension()?.to_str()?.to_ascii_lowercase();
    let stem = path
        .file_stem()?
        .to_str()?
        .chars()
        .map(|c| if c.is_control() || "/\\:*?\"<>|".contains(c) { ' ' } else { c })
        .collect::<String>();
    let stem = stem.split_whitespace().collect::<Vec<_>>().join(" ");
    let stem: String = stem.trim_start_matches('.').chars().take(MAX_STEM_CHARS).collect();
    (!stem.is_empty() && EXTENSIONS.contains(&extension.as_str())).then_some((stem, extension))
}

/// Write `contents` to a new file in the Downloads folder (the documents folder where there's none, as on iOS) and
/// return its path. Nothing is overwritten: when "Report.txt" exists, it becomes "Report (2).txt"
#[tauri::command]
pub fn export_save(app: AppHandle, file_name: String, contents: String) -> Result<String, String> {
    let (stem, extension) = clean_name(&file_name).ok_or_else(|| format!("Not a file name to save: {file_name:?}"))?;
    let folder = app
        .path()
        .download_dir()
        .or_else(|_| app.path().document_dir())
        .map_err(|e| format!("No folder to save in: {e}"))?;
    fs::create_dir_all(&folder).map_err(|e| format!("Could not open {}: {e}", folder.display()))?;

    for copy in 1..1000 {
        let name = if copy == 1 { format!("{stem}.{extension}") } else { format!("{stem} ({copy}).{extension}") };
        let path = folder.join(name);
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut file) => {
                file.write_all(contents.as_bytes()).map_err(|e| format!("Could not save {}: {e}", path.display()))?;
                return Ok(path.to_string_lossy().into_owned());
            }
            Err(e) if e.kind() == ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("Could not save {}: {e}", path.display())),
        }
    }
    Err(format!("{} already has too many files named {stem}", folder.display()))
}

#[cfg(test)]
mod tests {
    use super::clean_name;

    #[test]
    fn keeps_a_plain_title() {
        assert_eq!(clean_name("Solid-State Batteries.txt"), Some(("Solid-State Batteries".into(), "txt".into())));
    }

    #[test]
    fn strips_path_and_reserved_characters() {
        assert_eq!(clean_name("../../etc/passwd.txt"), Some(("passwd".into(), "txt".into())));
        assert_eq!(clean_name("What: is \"MCP\"?.txt"), Some(("What is MCP".into(), "txt".into())));
        assert_eq!(clean_name(".hidden.md"), Some(("hidden".into(), "md".into())));
    }

    #[test]
    fn refuses_other_types_and_empty_names() {
        assert_eq!(clean_name("report.sh"), None);
        assert_eq!(clean_name("report"), None);
        assert_eq!(clean_name("  .txt"), None);
    }
}
