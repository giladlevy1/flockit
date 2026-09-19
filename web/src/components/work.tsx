import clsx from "clsx";
import { Bot, CheckCircle2, CircleDashed, CircleDot, Clock3, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import { hueFor } from "../lib/format";
import type { PermissionProfile, PersonRef, RunStatus } from "../lib/types";
import { Avatar, Badge } from "./ui";

const STATUS: Record<RunStatus, { label: string; tone: "neutral" | "live" | "warn" | "bad" | "accent"; icon: ReactNode }> = {
  offered: { label: "Waiting for you", tone: "accent", icon: <CircleDot className="size-3" /> },
  queued: { label: "Queued", tone: "neutral", icon: <Clock3 className="size-3" /> },
  starting: { label: "Starting", tone: "warn", icon: <Loader2 className="size-3 animate-spin" /> },
  running: { label: "Running", tone: "live", icon: <span className="live-dot !size-1.5" /> },
  succeeded: { label: "Done", tone: "live", icon: <CheckCircle2 className="size-3" /> },
  failed: { label: "Failed", tone: "bad", icon: <XCircle className="size-3" /> },
  declined: { label: "Declined", tone: "neutral", icon: <MinusCircle className="size-3" /> },
  cancelled: { label: "Cancelled", tone: "neutral", icon: <CircleDashed className="size-3" /> },
};

export function statusLabel(status: RunStatus, forMe = false): string {
  if (status === "offered" && !forMe) return "Offered";
  return STATUS[status].label;
}

export function TaskStatus({ status, forMe = false }: { status: RunStatus; forMe?: boolean }) {
  const s = STATUS[status];
  return (
    <Badge tone={s.tone}>
      {s.icon}
      {statusLabel(status, forMe)}
    </Badge>
  );
}

export function BotAvatar({ id, size = 28 }: { id: string; size?: number }) {
  const hue = hueFor(id);
  return (
    <span
      aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-lg"
      style={{ width: size, height: size, background: `oklch(0.3 0.06 ${hue})`, color: `oklch(0.9 0.08 ${hue})` }}
    >
      <Bot style={{ width: size * 0.58, height: size * 0.58 }} strokeWidth={2} />
    </span>
  );
}

export function PersonChip({ person, size = 24, sub }: { person: PersonRef | null; size?: number; sub?: ReactNode }) {
  if (!person) return <span className="text-muted">Unassigned</span>;
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      {person.kind === "ai" ? <BotAvatar id={person.id} size={size} /> : <Avatar name={person.name} id={person.id} size={size} />}
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 truncate font-medium text-ink">
          {person.name}
          {person.kind === "ai" && <span className="rounded bg-ink px-1 py-px text-[9.5px] font-semibold tracking-wide text-bg">AI</span>}
        </span>
        {sub && <span className="block truncate text-xs text-muted">{sub}</span>}
      </span>
    </span>
  );
}

export const PROFILE_TEXT: Record<PermissionProfile, { label: string; hint: string }> = {
  read_only: { label: "Read only", hint: "Investigate and report. No file changes." },
  edit: { label: "Edit code", hint: "Edit files, run git and test commands. Anything else is denied." },
  full: { label: "Full access", hint: "Anything the agent decides. Only honoured in AI-developer sandboxes." },
};

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={clsx("grid gap-1 rounded-lg border border-line p-1", className)} style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-md px-2 py-1.5 text-[13px]",
            value === o.value ? "bg-ink font-medium text-bg" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={clsx(
        "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted",
        "focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none",
        props.className,
      )}
    />
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={clsx(
        "h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-sm text-ink focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none",
        props.className,
      )}
    />
  );
}

export function money(usd: number | null | undefined): string {
  if (usd == null) return "—";
  return usd < 1 ? `$${usd.toFixed(2)}` : `$${usd.toFixed(usd < 100 ? 2 : 0)}`;
}

export function tokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
