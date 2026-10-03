import { useState, type ReactNode } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import type { Platform } from "./contract";

export const PLATFORM_LABELS: Record<Platform, string> = {
  reference: "Reference",
  news: "News",
  academic: "Academic",
  community: "Community",
  industry: "Industry",
};

const PLATFORM_ICONS: Record<Platform, string> = {
  reference: "M2.5 3.6c2-.9 3.8-.8 5.5.6v8.9c-1.7-1.3-3.5-1.4-5.5-.6zM13.5 3.6c-2-.9-3.8-.8-5.5.6v8.9c1.7-1.3 3.5-1.4 5.5-.6z",
  news: "M2.5 3.5h8.5v8.25a1.25 1.25 0 0 0 1.25 1.25H3.75A1.25 1.25 0 0 1 2.5 11.75zM11 6h2.5v5.75a1.25 1.25 0 0 1-2.5 0M4.75 6.25h4M4.75 8.5h4M4.75 10.75h2.5",
  academic: "M1.5 6.25 8 3.25l6.5 3L8 9.25zM4.25 7.75v3.1c2.1 1.55 5.4 1.55 7.5 0v-3.1M14.5 6.25v3.5",
  community:
    "M2.5 4.25A1.25 1.25 0 0 1 3.75 3h5.5a1.25 1.25 0 0 1 1.25 1.25v3.5A1.25 1.25 0 0 1 9.25 9H5.5L3 11V9a1.25 1.25 0 0 1-.5-1zM10.5 6h1.75a1.25 1.25 0 0 1 1.25 1.25v3.5a1.25 1.25 0 0 1-.5 1V14L10.5 12H7.75a1.25 1.25 0 0 1-1.25-1.25V9",
  industry: "M2.5 13.5h11M4 11V8.5M7 11V6M10 11V7.5M13 11V3.5",
};

export function PlatformIcon({ platform }: { platform: Platform }) {
  return (
    <svg className="platform-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d={PLATFORM_ICONS[platform] ?? PLATFORM_ICONS.reference} />
    </svg>
  );
}

export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** The URL as an address bar shows it: host, then path, no scheme */
export function displayUrl(url: string): { host: string; rest: string } {
  try {
    const parsed = new URL(url);
    const rest = `${parsed.pathname === "/" ? "" : parsed.pathname}${parsed.search}`;
    return { host: parsed.hostname.replace(/^www\./, ""), rest: decodeURI(rest) };
  } catch {
    return { host: url, rest: "" };
  }
}

/** The site's icon, or its initial on a tile when the icon service has none */
export function Favicon({ url, size = 16 }: { url: string; size?: number }) {
  const host = hostname(url);
  const [failed, setFailed] = useState(false);
  if (failed || !host) {
    return (
      <span className="favicon favicon-letter" style={{ width: size, height: size, fontSize: size * 0.62 }} aria-hidden="true">
        {host.charAt(0).toUpperCase()}
      </span>
    );
  }
  return (
    <img
      className="favicon"
      src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=${size * 2}`}
      width={size}
      height={size}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

/** A plain link would navigate the app's webview away, so links open in the system browser */
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
        event.stopPropagation();
        openUrl(href).catch(() => {});
      }}
    >
      {children}
    </a>
  );
}
