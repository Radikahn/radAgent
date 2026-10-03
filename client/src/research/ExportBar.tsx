import { useState } from "react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { printReport, saveText, type ExportableReport } from "./exportReport";

type Status = { text: string; path?: string; failed?: boolean };

const SHOW_LABEL = /Mac/i.test(navigator.userAgent) ? "Show in Finder" : "Show in folder";

/** Where a saved file went, e.g. "Downloads" */
function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 2] ?? "the folder";
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/** Ends a finished report: save it as a PDF (through the print panel) or as a text file */
export function ExportBar({ report }: { report: ExportableReport }) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);

  async function exportPdf() {
    setBusy(true);
    setStatus(null);
    try {
      await printReport(report);
    } catch (error) {
      setStatus({ text: `Couldn't open the print panel: ${String(error)}`, failed: true });
    } finally {
      setBusy(false);
    }
  }

  async function exportText() {
    setBusy(true);
    setStatus(null);
    const result = await saveText(report);
    setBusy(false);
    switch (result.kind) {
      case "saved":
        setStatus({ text: `Saved ${fileName(result.path)} to ${folderName(result.path)}`, path: result.path });
        break;
      case "shared":
        setStatus({ text: "Shared the report as text" });
        break;
      case "copied":
        setStatus({ text: "Copied the report to the clipboard as text" });
        break;
      case "failed":
        setStatus({ text: `Couldn't save the report: ${result.message}`, failed: true });
        break;
      case "cancelled":
        break;
    }
  }

  return (
    <div className="report-export">
      <span className="report-export-label">Export</span>
      <button type="button" className="export-button" onClick={exportPdf} disabled={busy}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 1.75h5.25L12.5 5v9.25H4zM9.25 1.75V5h3.25" />
          <path d="M6 8.25h4.5M6 10.5h4.5M6 12.5h2.5" />
        </svg>
        PDF
      </button>
      <button type="button" className="export-button" onClick={exportText} disabled={busy}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3 3.5h10M3 6.5h10M3 9.5h10M3 12.5h6" />
        </svg>
        Text
      </button>
      {status && (
        <span key={status.text} className={`export-status materialize ${status.failed ? "failed" : ""}`} role="status">
          {status.text}
          {status.path && (
            <button type="button" className="quiet export-reveal" onClick={() => revealItemInDir(status.path!).catch(() => {})}>
              {SHOW_LABEL}
            </button>
          )}
        </span>
      )}
    </div>
  );
}
