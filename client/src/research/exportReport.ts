import { createElement } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";
import { citedIds, numberCitations, parseReport, sourceNumber } from "./parse";
import { hostname } from "./parts";
import { formatDate, PrintSheet, type ExportableReport } from "./PrintSheet";

export type { ExportableReport };

// ---- Text ----

/** Markdown's emphasis and links as plain text; lists, tables and paragraphs already read fine as they are */
function plain(markdown: string): string {
  return markdown
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?!\w)/g, "$1$2")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/!?\[([^\]]+)\]\(([^)\s]+)\)/g, "$1 ($2)")
    .replace(/^#{3,6}\s+/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const underline = (text: string, mark: string) => mark.repeat(Math.min(Math.max(text.length, 3), 72));

/** The report as a text file: numbered citations, each section's sources under it, every source's URL at the end */
export function reportText(report: ExportableReport): string {
  const known = new Map(report.sources.map((source) => [source.id, source]));
  const lines = [
    report.title,
    underline(report.title, "="),
    "",
    `Research report, ${formatDate(report.date)}. ${report.agents} research agents, ${report.sources.length} sources.`,
    "",
  ];

  for (const section of parseReport(report.text).sections) {
    if (section.heading) lines.push(section.heading, underline(section.heading, "-"), "");
    lines.push(plain(numberCitations(section.body, known)), "");
    const ids = citedIds(section.body, known);
    if (ids.length) {
      lines.push(`Sources: ${ids.map((id) => `[${sourceNumber(id)}] ${hostname(known.get(id)!.url)}`).join(", ")}`, "");
    }
  }

  lines.push("Sources", underline("Sources", "-"), "");
  for (const source of report.sources) {
    const published = source.published ? ` (${source.published})` : "";
    lines.push(`[${sourceNumber(source.id)}] ${source.title}${published}`, `    ${source.url}`);
  }
  return `${lines.join("\n")}\n`;
}

/** A file name from the report's title, without the characters file systems refuse */
function fileName(title: string, extension: string): string {
  const stem = title.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 100);
  return `${stem || "Research report"}.${extension}`;
}

export type SaveResult =
  | { kind: "saved"; path: string }
  | { kind: "shared" }
  | { kind: "copied" }
  | { kind: "cancelled" }
  | { kind: "failed"; message: string };

const inTauri = () => "__TAURI_INTERNALS__" in window;

/**
 * Save the report as a .txt file in Downloads, through the app's `export_save` command (src-tauri/src/export.rs);
 * a webview can't write files, and a browser-style download goes nowhere in a Tauri window. Where that command
 * isn't there (in a browser, say), the text is shared or copied instead so the button still does something useful
 */
export async function saveText(report: ExportableReport): Promise<SaveResult> {
  const contents = reportText(report);
  if (inTauri()) {
    try {
      return { kind: "saved", path: await invoke<string>("export_save", { fileName: fileName(report.title, "txt"), contents }) };
    } catch (error) {
      const message = String(error);
      // Only a missing command falls through to sharing; a real failure (a full disk, say) is reported
      if (!/not found|not allowed/i.test(message)) return { kind: "failed", message };
    }
  }

  if (typeof navigator.share === "function") {
    try {
      await navigator.share({ title: report.title, text: contents });
      return { kind: "shared" };
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return { kind: "cancelled" };
    }
  }
  try {
    await navigator.clipboard.writeText(contents);
    return { kind: "copied" };
  } catch {
    return { kind: "failed", message: "this window can't save files or reach the clipboard" };
  }
}

// ---- PDF ----

let sheet: Root | undefined;

/**
 * Open the print panel on the report, from which it saves as a PDF (on macOS, the panel's PDF menu)
 *
 * The report is drawn into its own element beside the app's root, and print.css hides everything else when
 * printing. That element stays (hidden) afterwards: the panel can render pages again while it's open
 */
export async function printReport(report: ExportableReport): Promise<void> {
  if (!sheet) {
    const element = document.createElement("div");
    element.id = "research-print";
    document.body.append(element);
    sheet = createRoot(element);
  }
  const root = sheet;
  flushSync(() => root.render(createElement(PrintSheet, { report })));

  // The panel suggests the document's title as the PDF's name
  const title = document.title;
  document.title = report.title;
  try {
    // A Tauri window answers print() with a promise; a browser prints synchronously and returns nothing
    await (window.print() as unknown);
  } finally {
    document.title = title;
  }
}
