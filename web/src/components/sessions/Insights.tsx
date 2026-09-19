import { CopyCheck, FolderGit2, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { hours, prettyModel, relativeTime, shortRepo, taskLabel, vendorLabel } from "../../lib/format";
import type { Summary } from "../../lib/types";
import { Card } from "../ui";
import { MODEL_COLORS } from "./StatusBadge";

function Panel({ icon, title, hint, children }: { icon: ReactNode; title: string; hint: string; children: ReactNode }) {
  return (
    <Card className="flex min-h-[200px] flex-col p-4">
      <div className="mb-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <span className="text-muted">{icon}</span>
          {title}
        </div>
        <p className="mt-0.5 text-xs text-muted">{hint}</p>
      </div>
      <div className="flex-1">{children}</div>
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="flex h-full min-h-[100px] items-center justify-center px-4 text-center text-xs text-muted">{children}</div>;
}

export function Overlaps({ items, onPick }: { items: Summary["overlaps"]; onPick: (task: string) => void }) {
  return (
    <Panel
      icon={<CopyCheck className="size-4" />}
      title="Same ticket, several people"
      hint="Work on one task spread across more than one person's agent sessions."
    >
      {items.length === 0 ? (
        <Empty>No ticket was worked by more than one person in this range.</Empty>
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {items.map((o) => (
            <li key={o.task_ref}>
              <button
                onClick={() => onPick(o.task_ref)}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-surface-2"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[12.5px] font-medium text-ink">{taskLabel(o.task_ref)}</span>
                  <span className="block truncate text-xs text-muted">{o.people.join(", ")}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="tabular block text-[13px] font-medium text-ink">{hours(o.hours)}</span>
                  <span className="block text-[11px] text-muted">{relativeTime(o.last_seen_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function TopRepos({ items, onPick }: { items: Summary["top_repos"]; onPick: (repo: string) => void }) {
  const max = Math.max(...items.map((r) => r.hours), 0.01);
  return (
    <Panel icon={<FolderGit2 className="size-4" />} title="Where agent time goes" hint="Repositories by total session time.">
      {items.length === 0 ? (
        <Empty>No repository activity yet.</Empty>
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {items.slice(0, 6).map((r) => (
            <li key={r.repo}>
              <button onClick={() => onPick(r.repo)} className="group w-full rounded-lg px-2 py-1.5 text-left hover:bg-surface-2">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="truncate font-mono text-[12.5px] text-ink">{shortRepo(r.repo)}</span>
                  <span className="tabular shrink-0 text-[12.5px] text-ink-2">
                    {hours(r.hours)} <span className="text-muted">· {r.people}p</span>
                  </span>
                </span>
                <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-surface-2 group-hover:bg-line">
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(r.hours / max) * 100}%` }} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function ModelMix({ items, onPick }: { items: Summary["by_agent"]; onPick: (model: string) => void }) {
  const total = items.reduce((acc, i) => acc + i.sessions, 0);
  return (
    <Panel
      icon={<Sparkles className="size-4" />}
      title="Agent and model mix"
      hint="What you are actually running, by share of sessions."
    >
      {items.length === 0 ? (
        <Empty>No agent sessions yet.</Empty>
      ) : (
        <>
          <div className="mb-3 flex h-2.5 overflow-hidden rounded-full bg-surface-2">
            {items.map((m, i) => (
              <span
                key={`${m.vendor}-${m.model}`}
                title={`${prettyModel(m.model)}: ${m.sessions} sessions`}
                style={{ width: `${(m.sessions / total) * 100}%`, background: MODEL_COLORS[i % MODEL_COLORS.length] }}
                className="h-full border-r-2 border-surface last:border-r-0"
              />
            ))}
          </div>
          <ul className="-mx-2 space-y-0.5">
            {items.slice(0, 5).map((m, i) => (
              <li key={`${m.vendor}-${m.model}`}>
                <button
                  onClick={() => m.model && onPick(m.model)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-surface-2"
                >
                  <span className="size-2.5 shrink-0 rounded-sm" style={{ background: MODEL_COLORS[i % MODEL_COLORS.length] }} />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                    {prettyModel(m.model)} <span className="text-muted">· {vendorLabel(m.vendor)}</span>
                  </span>
                  <span className="tabular shrink-0 text-[12.5px] text-ink-2">
                    {Math.round((m.sessions / total) * 100)}%
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
