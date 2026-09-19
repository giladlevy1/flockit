import clsx from "clsx";
import type { ReactNode } from "react";

import { hours } from "../../lib/format";
import type { Summary } from "../../lib/types";
import { Card } from "../ui";

function Kpi({
  label,
  value,
  sub,
  children,
  tone,
  onClick,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  children?: ReactNode;
  tone?: "live" | "warn";
  onClick?: () => void;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Card className={clsx("relative overflow-hidden", onClick && "transition-colors hover:border-line-strong")}>
      <Tag onClick={onClick} className="block h-full w-full p-4 text-left">
        <div className="flex items-center gap-2 text-[12.5px] font-medium text-muted">{label}</div>
        <div
          className={clsx(
            "tabular mt-2 text-[28px] leading-none font-semibold tracking-tight",
            tone === "live" ? "text-live" : tone === "warn" ? "text-warn" : "text-ink",
          )}
        >
          {value}
        </div>
        {sub && <div className="mt-1.5 truncate text-xs text-muted">{sub}</div>}
        {children}
      </Tag>
    </Card>
  );
}

function DailyBars({ daily }: { daily: Summary["daily"] }) {
  if (daily.length < 2) return null;
  const max = Math.max(...daily.map((d) => d.sessions), 1);
  const recent = daily.slice(-30);
  return (
    <div className="absolute right-4 bottom-4 hidden h-9 items-end gap-[2px] sm:flex" aria-hidden>
      {recent.map((d) => (
        <div
          key={d.day}
          title={`${d.day}: ${d.sessions} sessions`}
          className="w-[5px] rounded-[1.5px] bg-accent/70"
          style={{ height: `${Math.max(8, (d.sessions / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

export function Kpis({
  summary,
  rangeLabel,
  onLive,
  onAbandoned,
}: {
  summary: Summary;
  rangeLabel: string;
  onLive: () => void;
  onAbandoned: () => void;
}) {
  const abandonedPct = summary.sessions ? Math.round((summary.outcomes.abandoned / summary.sessions) * 100) : 0;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Kpi
        label={
          <>
            {summary.live_sessions > 0 ? <span className="live-dot" /> : <span className="size-2 rounded-full bg-line-strong" />}
            Live now
          </>
        }
        value={summary.live_sessions}
        sub={summary.live_sessions ? `${summary.live_people} ${summary.live_people === 1 ? "person" : "people"} working with agents` : "No agent is running"}
        tone={summary.live_sessions ? "live" : undefined}
        onClick={onLive}
      />
      <Kpi label="Sessions" value={summary.sessions.toLocaleString()} sub={rangeLabel}>
        <DailyBars daily={summary.daily} />
      </Kpi>
      <Kpi label="Agent time" value={hours(summary.agent_hours)} sub={`${summary.turns.toLocaleString()} agent turns`} />
      <Kpi
        label="People"
        value={summary.people}
        sub={`across ${summary.repos} ${summary.repos === 1 ? "repo" : "repos"}`}
      />
      <Kpi
        label="Abandoned"
        value={`${abandonedPct}%`}
        sub={`${summary.outcomes.abandoned} sessions went quiet and never ended`}
        tone={abandonedPct >= 20 ? "warn" : undefined}
        onClick={onAbandoned}
      />
    </div>
  );
}
