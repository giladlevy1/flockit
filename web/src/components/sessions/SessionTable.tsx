import clsx from "clsx";
import { GitBranch } from "lucide-react";

import { duration, prettyModel, relativeTime, shortRepo, taskHref, taskLabel, vendorLabel } from "../../lib/format";
import type { Session } from "../../lib/types";
import { Avatar } from "../ui";
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
      <table className="w-full min-w-[980px] border-collapse text-sm">
        <thead className="border-b border-line bg-surface-2/60">
          <tr>
            {showOwner && <Th className="pl-4">Person</Th>}
            <Th className={showOwner ? "" : "pl-4"}>Agent</Th>
            <Th>Repo and branch</Th>
            <Th>Task</Th>
            <Th>Started</Th>
            <Th className="text-right">Duration</Th>
            <Th className="text-right">Turns</Th>
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
                      <Avatar name={s.owner.name} id={s.owner.id} />
                      <div className="min-w-0">
                        <div className="truncate font-medium text-ink">{s.owner.name}</div>
                        <div className="truncate text-xs text-muted">{s.owner.teams.join(", ") || "No team"}</div>
                      </div>
                    </div>
                  </td>
                )}
                <td className={clsx("px-3 py-2.5", !showOwner && "pl-4")}>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-ink">{prettyModel(s.agent_model)}</span>
                    <OriginBadge origin={s.origin} />
                  </div>
                  <div className="text-xs text-muted">{vendorLabel(s.agent_vendor)}</div>
                </td>
                <td className="max-w-[280px] px-3 py-2.5">
                  <div className="truncate font-mono text-[12.5px] text-ink">{shortRepo(s.repo) || <span className="text-muted">No repo</span>}</div>
                  {s.branch && (
                    <div className="flex items-center gap-1 truncate font-mono text-[11.5px] text-muted">
                      <GitBranch className="size-3 shrink-0" />
                      <span className="truncate">{s.branch}</span>
                    </div>
                  )}
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
                <td className="tabular px-3 py-2.5 text-right text-ink-2">{s.turn_count}</td>
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
