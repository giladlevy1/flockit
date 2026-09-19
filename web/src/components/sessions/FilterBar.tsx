import clsx from "clsx";
import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

import { RANGES, type RangeValue, type useFilters } from "../../lib/filters";
import { prettyModel, shortRepo, taskLabel, vendorLabel } from "../../lib/format";
import type { Facets } from "../../lib/types";
import { MultiSelect } from "../MultiSelect";
import { Avatar } from "../ui";

export function RangePicker({ value, onChange }: { value: RangeValue; onChange: (r: RangeValue) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5" role="radiogroup" aria-label="Date range">
      {RANGES.map((r) => (
        <button
          key={r.value}
          role="radio"
          aria-checked={value === r.value}
          onClick={() => onChange(r.value)}
          className={clsx(
            "rounded-md px-2.5 py-1 text-[13px] transition-colors",
            value === r.value ? "bg-ink text-bg font-medium" : "text-muted hover:text-ink",
          )}
        >
          {r.value === "all" ? "All" : r.value}
        </button>
      ))}
    </div>
  );
}

export function FilterBar({
  filters,
  facets,
  scope,
}: {
  filters: ReturnType<typeof useFilters>;
  facets: Facets | undefined;
  scope: "organisation" | "team" | "self";
}) {
  const { state, setList, setQuery, setTaskRef, clearAll, active } = filters;
  const [q, setQ] = useState(state.q);

  useEffect(() => setQ(state.q), [state.q]);
  useEffect(() => {
    const id = setTimeout(() => q !== state.q && setQuery(q), 250);
    return () => clearTimeout(id);
  }, [q, state.q, setQuery]);

  const f = facets ?? { people: [], teams: [], repos: [], vendors: [], models: [] };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search person, repo, branch, ticket…"
          aria-label="Search sessions"
          className="h-8 w-[260px] rounded-lg border border-line bg-surface pr-2.5 pl-8 text-[13px] placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none"
        />
      </div>
      {scope !== "self" && (
        <MultiSelect
          label="Person"
          value={state.lists.owner}
          onChange={(v) => setList("owner", v)}
          options={f.people.map((p) => ({
            value: p.id,
            label: p.name,
            hint: p.email,
            icon: <Avatar name={p.name} id={p.id} size={20} />,
          }))}
        />
      )}
      {scope !== "self" && f.teams.length > 0 && (
        <MultiSelect
          label="Team"
          value={state.lists.team}
          onChange={(v) => setList("team", v)}
          options={f.teams.map((t) => ({ value: t.id, label: t.name }))}
        />
      )}
      <MultiSelect
        label="Worker"
        value={state.lists.worker}
        onChange={(v) => setList("worker", v)}
        options={[
          { value: "human", label: "People", hint: "their own sessions" },
          { value: "ai", label: "AI developers", hint: "sessions run on runners" },
        ]}
      />
      <MultiSelect
        label="Repo"
        value={state.lists.repo}
        onChange={(v) => setList("repo", v)}
        options={f.repos.map((r) => ({ value: r, label: shortRepo(r), hint: r.split("/")[0] }))}
      />
      <MultiSelect
        label="Agent"
        value={state.lists.vendor}
        onChange={(v) => setList("vendor", v)}
        options={f.vendors.map((v) => ({ value: v, label: vendorLabel(v) }))}
      />
      <MultiSelect
        label="Model"
        value={state.lists.model}
        onChange={(v) => setList("model", v)}
        options={f.models.map((m) => ({ value: m, label: prettyModel(m), hint: m }))}
      />
      <MultiSelect
        label="Status"
        value={state.lists.status}
        onChange={(v) => setList("status", v)}
        options={[
          { value: "live", label: "Live", hint: "active in the last 15 min" },
          { value: "idle", label: "Idle", hint: "open, but quiet" },
          { value: "ended", label: "Ended" },
        ]}
      />
      <MultiSelect
        label="Outcome"
        value={state.lists.outcome}
        onChange={(v) => setList("outcome", v)}
        options={[
          { value: "completed", label: "Completed", hint: "ended by the developer" },
          { value: "abandoned", label: "Abandoned", hint: "went quiet, never ended" },
          { value: "errored", label: "Errored" },
          { value: "unknown", label: "Unknown" },
        ]}
      />
      {state.task_ref && (
        <span className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-accent/40 bg-accent-soft pr-1.5 pl-2.5 text-[13px] text-accent-ink">
          Ticket · <span className="font-mono">{taskLabel(state.task_ref)}</span>
          <button onClick={() => setTaskRef("")} aria-label="Clear ticket filter" className="rounded p-0.5 hover:bg-accent/15">
            <X className="size-3.5" />
          </button>
        </span>
      )}
      {active && (
        <button onClick={clearAll} className="h-8 rounded-lg px-2 text-[13px] text-muted hover:text-ink">
          Clear all
        </button>
      )}
    </div>
  );
}
