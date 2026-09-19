const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeTime(iso: string, now = Date.now()): string {
  const diff = (new Date(iso).getTime() - now) / 1000;
  const abs = Math.abs(diff);
  if (abs < 45) return "just now";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 7) return rtf.format(Math.round(diff / 86400), "day");
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  if (h < 24) return rm ? `${h}h ${rm}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export function hours(h: number): string {
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 10) return `${h.toFixed(1)}h`;
  return `${Math.round(h).toLocaleString()}h`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** A stable, pleasant hue per person so avatars are recognisable at a glance. */
export function hueFor(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}

export function shortRepo(repo: string | null): string {
  if (!repo) return "";
  const parts = repo.split("/");
  return parts.length >= 3 ? parts.slice(1).join("/") : repo;
}

export function prettyModel(model: string | null): string {
  if (!model) return "Unknown model";
  const m = model.match(/^claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d+))?(?:-\d{8})?(\[1m\])?$/);
  if (m) {
    const family = m[1][0].toUpperCase() + m[1].slice(1);
    const version = m[3] ? `${m[2]}.${m[3]}` : m[2];
    return `${family} ${version}${m[4] ? " 1M" : ""}`;
  }
  return model;
}

export function vendorLabel(vendor: string): string {
  const known: Record<string, string> = {
    "claude-code": "Claude Code",
    codex: "Codex",
    cursor: "Cursor",
    "gemini-cli": "Gemini CLI",
  };
  return known[vendor] ?? vendor;
}

export function taskHref(ref: string | null): string | null {
  if (!ref) return null;
  return /^https?:\/\//.test(ref) ? ref : null;
}

export function taskLabel(ref: string): string {
  if (!/^https?:\/\//.test(ref)) return ref;
  try {
    const u = new URL(ref);
    const gh = u.pathname.match(/^\/([^/]+)\/([^/]+)\/(issues|pull)\/(\d+)/);
    if (gh) return `${gh[2]}#${gh[4]}`;
    const last = u.pathname.split("/").filter(Boolean).pop();
    return last ?? u.host;
  } catch {
    return ref;
  }
}
