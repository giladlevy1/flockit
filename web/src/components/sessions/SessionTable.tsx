import clsx from "clsx";
import { GitBranch } from "lucide-react";

import { duration, prettyModel, relativeTime, shortRepo, taskHref, taskLabel, vendorLabel } from "../../lib/format";
import type { Session } from "../../lib/types";
import { Avatar } from "../ui";
import { BotAvatar, tokens } from "../work";
import { OriginBadge, StatusBadge } from "./StatusBadge";

export function liveDuration(s: Session, now: number): number {
  if (s.status !== "live") return s.duration_seconds;
  return Math.max(s.duration_seconds, (now - new Date(s.started_at).getTime()) / 1000);
}

function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={clsx("px-3 py-2.5 text-left text-[11.5px] font-medium tracking-wide text-muted uppercase", className)}>
      {children}
    </th>
  );
}

export function SessionTable({
  items,
  now,
  selected,
  onSelect,
  showOwner,
}: {
  items: Session[];
  now: number;
  selected: string | null;
  onSelect: (id: string) => void;
  showOwner: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1060px] border-collapse text-sm">
        <thead className="border-b border-line bg-surface-2/60">
          <tr>
            {showOwner && <Th className="pl-4">Who</Th>}
            <Th className={showOwner ? "" : "pl-4"}>Session</Th>
            <Th>Agent</Th>
            <Th>Ticket</Th>
            <Th>Started</Th>
            <Th className="text-right">Duration</Th>
            <Th className="text-right">Tokens</Th>
            <Th className="pr-4">How it ended</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => {
            const href = taskHref(s.task_ref);
            return (
              <tr
                key={s.id}
                onClick={() => onSelect(s.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(s.id))}
                tabIndex={0}
                aria-selected={selected === s.id}
                className={clsx(
                  "cursor-pointer border-b border-line last:border-b-0 transition-colors outline-none",
                  selected === s.id ? "bg-accent-soft/60" : "hover:bg-surface-2/70 focus-visible:bg-surface-2",
                )}
              >
                {showOwner && (
                  <td className="py-2.5 pr-3 pl-4">
                    <div className="flex items-center gap-2.5">
                      {s.actor?.kind === "ai" ? <BotAvatar id={s.actor.id} /> : <Avatar name={s.owner.name} id={s.owner.id} />}
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 truncate font-medium text-ink">
                          {s.actor?.kind === "ai" ? s.actor.name : s.owner.name}
                          {s.actor?.kind === "ai" && <span className="rounded bg-ink px-1 py-px text-[9.5px] font-semibold text-bg">AI</span>}
                        </div>
                        <div className="truncate text-xs text-muted">
                          {s.actor?.kind === "ai" ? `for ${s.owner.name}` : s.owner.teams.join(", ") || "No team"}
                        </div>
                      </div>
                    </div>
                  </td>
                )}
                <td className={clsx("max-w-[340px] px-3 py-2.5", !showOwner && "pl-4")}>
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-ink">{s.title ?? <span className="text-muted">{shortRepo(s.repo) || "Untitled"}</span>}</span>
                    <OriginBadge origin={s.origin} />
                  </div>
                  <div className="flex items-center gap-1 truncate font-mono text-[11.5px] text-muted">
                    <span className="truncate">{shortRepo(s.repo) || "no repo"}</span>
                    {s.branch && (
                      <>
                        <GitBranch className="ml-1 size-3 shrink-0" />
                        <span className="truncate">{s.branch}</span>
                      </>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <div className="font-medium text-ink">{prettyModel(s.agent_model)}</div>
                  <div className="text-xs text-muted">{vendorLabel(s.agent_vendor)}</div>
                </td>
                <td className="px-3 py-2.5">
                  {s.task_ref ? (
                    href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer noopener"
                        onClick={(e) => e.stopPropagation()}
                        className="font-mono text-[12.5px] text-accent-ink hover:underline"
                      >
                        {taskLabel(s.task_ref)}
                      </a>
                    ) : (
                      <span className="font-mono text-[12.5px] text-ink">{s.task_ref}</span>
                    )
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap text-ink-2" title={new Date(s.started_at).toLocaleString()}>
                  {relativeTime(s.started_at, now)}
                </td>
                <td className="tabular px-3 py-2.5 text-right whitespace-nowrap text-ink">{duration(liveDuration(s, now))}</td>
                <td className="tabular px-3 py-2.5 text-right text-ink-2" title={`${s.tokens_output.toLocaleString()} output, ${(s.tokens_input + s.tokens_cache_read + s.tokens_cache_write).toLocaleString()} input`}>
                  {s.tokens_output || s.tokens_input ? tokens(s.tokens_input + s.tokens_cache_read + s.tokens_cache_write + s.tokens_output) : <span className="text-muted">—</span>}
                </td>
                <td className="py-2.5 pr-4 pl-3">
                  <StatusBadge s={s} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
