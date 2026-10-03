import type { ReactNode } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";

export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** A plain link would navigate the app's webview away, so links open in the system browser or maps app */
export function External({
  href,
  className,
  title,
  children,
}: {
  href: string;
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      className={className}
      title={title}
      onClick={(event) => {
        event.preventDefault();
        openUrl(href).catch(() => {});
      }}
    >
      {children}
    </a>
  );
}
