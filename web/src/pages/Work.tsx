import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Search, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { FilterBar, RangePicker } from "../components/sessions/FilterBar";
import { ModelMix, Overlaps, TopRepos } from "../components/sessions/Insights";
import { Kpis } from "../components/sessions/Kpis";
import { SessionDrawer } from "../components/sessions/SessionDrawer";
import { SessionTable } from "../components/sessions/SessionTable";
import { NewTaskDialog } from "../components/tasks/NewTaskDialog";
import { Attention } from "../components/work/Attention";
import { GettingStarted } from "../components/work/GettingStarted";
import { Button, Card, Input, PageHeader, Spinner } from "../components/ui";
import { Segmented } from "../components/work";
import { api, qs } from "../lib/api";
import { RANGES, useFilters } from "../lib/filters";
import type { Facets, Me, SessionPage, Summary } from "../lib/types";
import { useNow } from "../lib/useNow";

const PAGE_SIZE = 50;
const POLL_MS = 5000;

type Scope = "mine" | "teams" | "all";

/**
 * Home. One question: what has been happening in my work?
 *
 * Sessions — mine, my teams', or the organisation's — and nothing else above them except
 * what actually needs a decision. The numbers live one tab away, because a developer
 * opening this page wants their work, not a dashboard.
 */
export function WorkPage({ me }: { me: Me }) {
  const filters = useFilters();
  const { apiParams, state, page } = filters;
  const [params, setParams] = useSearchParams();
  const [showFilters, setShowFilters] = useState(false);
  const [newTask, setNewTask] = useState(false);

  const canSeeOthers = me.scope !== "self";
  const scope: Scope = canSeeOthers ? ((params.get("scope") as Scope) ?? "all") : "mine";
  const tab = params.get("tab") === "insights" && canSeeOthers ? "insights" : "sessions";
  const setParam = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        next.delete("page");
        return next;
      },
      { replace: true },
    );

  // "Mine" and "My teams" are ordinary filters, so a view stays a shareable link.
  const scoped = {
    ...apiParams,
    owner: scope === "mine" ? [me.user.id] : apiParams.owner,
    team: scope === "teams" ? me.user.teams.map((t) => t.id) : apiParams.team,
  };

  const list = useQuery({
    queryKey: ["sessions", scoped, page],
    queryFn: () => api<SessionPage>(`/api/sessions${qs({ ...scoped, limit: PAGE_SIZE, offset: page * PAGE_SIZE })}`),
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({
    queryKey: ["summary", scoped],
    queryFn: () => api<Summary>(`/api/sessions/summary${qs(scoped)}`),
    refetchInterval: POLL_MS,
    enabled: tab === "insights",
    placeholderData: keepPreviousData,
  });
  const facets = useQuery({ queryKey: ["facets"], queryFn: () => api<Facets>("/api/sessions/facets"), refetchInterval: 60_000 });

  // A brand new organisation has nothing to filter, sort or page through. Until the first
  // session arrives, the page is the setup, not an empty table with controls above it.
  const empty = !filters.active && (list.data?.total ?? 0) === 0 && (facets.data?.vendors.length ?? 0) === 0;
  const anyLive = (list.data?.items ?? []).some((s) => s.status === "live");
  const now = useNow(anyLive || !!filters.selected);
  const rangeLabel = RANGES.find((r) => r.value === state.range)?.label ?? "";

  const pick = (key: "owner" | "repo" | "model" | "task_ref", value: string) => {
    if (key === "task_ref") filters.setTaskRef(value);
    else filters.setList(key, [value]);
    filters.select(null);
  };

  return (
    <div>
      <PageHeader
        title={empty ? `Welcome, ${me.user.name.split(" ")[0]}` : scope === "mine" ? "Your work" : scope === "teams" ? "Your teams" : "All work"}
        sub={
          empty
            ? "Four steps and your SDLC runs on this: every session recorded, work that survives a closed laptop, and agents that test what they write."
            : "Every coding session in your SDLC, human and AI, with the full conversation behind it."
        }
        actions={
          empty ? null : (
            <Button variant="primary" onClick={() => setNewTask(true)}>
              <Plus className="size-4" /> New task
            </Button>
          )
        }
      />

      {(!me.onboarded || empty) && <GettingStarted me={me} />}
      <Attention me={me} />

      {empty && <Waiting />}

      <div className={"mb-3 flex flex-wrap items-center gap-2" + (empty ? " hidden" : "")}>
        {canSeeOthers && (
          <Segmented
            value={scope}
            onChange={(v) => setParam("scope", v === "all" ? null : v)}
            options={[
              { value: "mine", label: "Mine" },
              { value: "teams", label: "My teams" },
              { value: "all", label: "Everyone" },
            ]}
          />
        )}
        {canSeeOthers && <span className="mx-0.5 hidden h-5 w-px bg-line sm:block" aria-hidden />}
        {canSeeOthers && (
          <Segmented
            value={tab}
            onChange={(v) => setParam("tab", v === "sessions" ? null : v)}
            options={[
              { value: "sessions", label: "Sessions" },
              { value: "insights", label: "Insights" },
            ]}
          />
        )}
        <div className="relative ml-auto w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted" />
          <Input
            value={state.q}
            onChange={(e) => filters.setQuery(e.target.value)}
            placeholder="Search titles, repos, tickets…"
            className="pl-8"
            aria-label="Search sessions"
          />
        </div>
        <RangePicker value={state.range} onChange={filters.setRange} />
        <Button
          size="sm"
          variant={showFilters || filters.active ? "secondary" : "ghost"}
          onClick={() => setShowFilters((v) => !v)}
          aria-expanded={showFilters}
        >
          <SlidersHorizontal className="size-4" /> Filters
        </Button>
      </div>

      {empty ? null : tab === "insights" ? (
        <div className="space-y-3">
          {summary.data ? (
            <>
              <Kpis
                summary={summary.data}
                rangeLabel={state.range === "all" ? "all time" : `in the last ${rangeLabel.toLowerCase()}`}
                onLive={() => filters.setList("status", ["live"])}
                onAbandoned={() => filters.setList("outcome", ["abandoned"])}
              />
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                <Overlaps items={summary.data.overlaps} onPick={(t) => filters.setTaskRef(t)} />
                <TopRepos items={summary.data.top_repos} onPick={(r) => filters.setList("repo", [r])} />
                <ModelMix items={summary.data.by_agent} onPick={(m) => filters.setList("model", [m])} />
              </div>
              <p className="px-1 text-xs text-muted">
                Everything here comes from the same sessions below: people and AI developers in one record.
              </p>
            </>
          ) : (
            <div className="flex h-48 items-center justify-center text-muted">
              <Spinner />
            </div>
          )}
        </div>
      ) : (
        <Card className="overflow-hidden">
          {showFilters && (
            <div className="border-b border-line px-4 py-3">
              <FilterBar filters={filters} facets={facets.data} scope={me.scope} />
            </div>
          )}
          {list.isLoading ? (
            <div className="flex h-48 items-center justify-center text-muted">
              <Spinner />
            </div>
          ) : list.data && list.data.items.length > 0 ? (
            <>
              <SessionTable
                items={list.data.items}
                now={now}
                selected={filters.selected}
                onSelect={(id) => filters.select(id)}
                showOwner={scope !== "mine"}
              />
              <Pager page={page} total={list.data.total} onPage={filters.setPage} />
            </>
          ) : (
            <Empty mine={scope === "mine"} filtered={filters.active} onClear={filters.clearAll} />
          )}
        </Card>
      )}

      {filters.selected && (
        <SessionDrawer id={filters.selected} now={now} onClose={() => filters.select(null)} onFilter={pick} />
      )}
      <NewTaskDialog me={me} open={newTask} onClose={() => setNewTask(false)} />
    </div>
  );
}

/**
 * The pause between finishing the setup and seeing the point of it. Rather than an empty
 * table, say exactly what will happen and show that we are watching for it.
 */
function Waiting() {
  return (
    <Card className="mb-6 flex flex-col items-center gap-2 px-6 py-12 text-center">
      <span className="flex items-center gap-2 text-sm font-medium">
        <Spinner className="size-4" /> Waiting for the first session
      </span>
      <p className="max-w-lg text-sm leading-relaxed text-muted">
        Run <span className="font-mono text-ink">claude</span> on a connected machine and it appears here within
        seconds — the prompts, the commands, the files it touched and what it cost. Everything else in Flockit is built
        on top of that record.
      </p>
      <Link to="/connect" className="mt-2 text-sm text-accent-ink hover:underline">
        Connect a machine
      </Link>
    </Card>
  );
}

function Empty({ mine, filtered, onClear }: { mine: boolean; filtered: boolean; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <p className="font-medium">{filtered ? "No sessions match" : mine ? "No sessions yet" : "Nothing here yet"}</p>
      <p className="max-w-sm text-sm text-muted">
        {filtered ? (
          "Try a longer date range or fewer filters."
        ) : (
          <>
            Sessions appear the moment someone runs Claude Code on a connected machine, or an AI developer picks up a
            task.{" "}
            <Link to="/connect" className="text-accent-ink hover:underline">
              Connect this machine
            </Link>
            .
          </>
        )}
      </p>
      {filtered && (
        <Button size="sm" className="mt-2" onClick={onClear}>
          Clear filters
        </Button>
      )}
    </div>
  );
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (n: number) => void }) {
  const pages = Math.ceil(total / PAGE_SIZE);
  const from = page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[13px] text-muted">
      <span className="tabular">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()} sessions
      </span>
      {pages > 1 && (
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => onPage(page - 1)} aria-label="Previous page">
            <ChevronLeft className="size-4" />
          </Button>
          <span className="tabular px-1">
            {page + 1} / {pages}
          </span>
          <Button size="sm" variant="ghost" disabled={page >= pages - 1} onClick={() => onPage(page + 1)} aria-label="Next page">
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
