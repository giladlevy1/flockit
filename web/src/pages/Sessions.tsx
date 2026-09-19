import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronLeft, ChevronRight, Radio } from "lucide-react";
import { Link } from "react-router";

import { FilterBar, RangePicker } from "../components/sessions/FilterBar";
import { ModelMix, Overlaps, TopRepos } from "../components/sessions/Insights";
import { Kpis } from "../components/sessions/Kpis";
import { SessionDrawer } from "../components/sessions/SessionDrawer";
import { SessionTable } from "../components/sessions/SessionTable";
import { Button, Card, PageHeader, Spinner } from "../components/ui";
import { api, qs } from "../lib/api";
import { RANGES, useFilters } from "../lib/filters";
import type { Facets, Me, SessionPage, Summary } from "../lib/types";
import { useNow } from "../lib/useNow";

const PAGE_SIZE = 50;
const POLL_MS = 5000;

const SCOPE_TEXT = {
  organisation: "Every coding session across the organisation, human and AI.",
  team: "Every coding session by you and the people on your teams.",
  self: "Your own coding sessions. Leads and admins see their teams and the organisation.",
};

export function SessionsPage({ me }: { me: Me }) {
  const filters = useFilters();
  const { apiParams, state, page } = filters;

  const summary = useQuery({
    queryKey: ["summary", apiParams],
    queryFn: () => api<Summary>(`/api/sessions/summary${qs(apiParams)}`),
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
  const list = useQuery({
    queryKey: ["sessions", apiParams, page],
    queryFn: () => api<SessionPage>(`/api/sessions${qs({ ...apiParams, limit: PAGE_SIZE, offset: page * PAGE_SIZE })}`),
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
  const facets = useQuery({
    queryKey: ["facets"],
    queryFn: () => api<Facets>("/api/sessions/facets"),
    refetchInterval: 60_000,
  });

  const anyLive = (list.data?.items ?? []).some((s) => s.status === "live");
  const now = useNow(anyLive || !!filters.selected);
  const rangeLabel = RANGES.find((r) => r.value === state.range)?.label ?? "";
  const neverSeenAnything = summary.data && facets.data && facets.data.vendors.length === 0;

  const pick = (key: "owner" | "repo" | "model" | "task_ref", value: string) => {
    if (key === "task_ref") filters.setTaskRef(value);
    else filters.setList(key, [value]);
    filters.select(null);
  };

  return (
    <div>
      <PageHeader
        title="Sessions"
        sub={SCOPE_TEXT[me.scope]}
        actions={<RangePicker value={state.range} onChange={filters.setRange} />}
      />

      {neverSeenAnything ? (
        <FirstRun me={me} />
      ) : (
        <>
          {summary.data ? (
            <Kpis
              summary={summary.data}
              rangeLabel={`in the last ${rangeLabel.toLowerCase()}`.replace("last all time", "all time")}
              onLive={() => filters.setList("status", ["live"])}
              onAbandoned={() => filters.setList("outcome", ["abandoned"])}
            />
          ) : (
            <div className="h-[106px]" />
          )}

          {summary.data && (
            <div className="mt-3 grid gap-3 lg:grid-cols-3">
              <Overlaps items={summary.data.overlaps} onPick={(t) => filters.setTaskRef(t)} />
              <TopRepos items={summary.data.top_repos} onPick={(r) => filters.setList("repo", [r])} />
              <ModelMix items={summary.data.by_agent} onPick={(m) => filters.setList("model", [m])} />
            </div>
          )}

          <Card className="mt-6 overflow-hidden">
            <div className="border-b border-line px-4 py-3">
              <FilterBar filters={filters} facets={facets.data} scope={me.scope} />
            </div>
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
                  showOwner={me.scope !== "self"}
                />
                <Pager page={page} total={list.data.total} onPage={filters.setPage} />
              </>
            ) : (
              <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
                <p className="font-medium">No sessions match</p>
                <p className="max-w-sm text-sm text-muted">
                  Try a longer date range or fewer filters.
                </p>
                {filters.active && (
                  <Button size="sm" className="mt-2" onClick={filters.clearAll}>
                    Clear filters
                  </Button>
                )}
              </div>
            )}
          </Card>
        </>
      )}

      {filters.selected && (
        <SessionDrawer id={filters.selected} now={now} onClose={() => filters.select(null)} onFilter={pick} />
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

function FirstRun({ me }: { me: Me }) {
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-8 p-8 md:grid-cols-[1.2fr_1fr] md:p-10">
        <div>
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-accent-soft text-accent">
            <Radio className="size-5" />
          </span>
          <h2 className="mt-4 text-xl font-semibold tracking-tight">Waiting for the first session</h2>
          <p className="mt-2 max-w-md text-[15px] leading-relaxed text-muted">
            Install the collector on a machine that runs Claude Code. Its next session shows up here within seconds,
            with the person, agent, model, repo, branch and ticket.
          </p>
          <Link to="/connect">
            <Button variant="primary" className="mt-6">
              Connect Claude Code <ArrowRight className="size-4" />
            </Button>
          </Link>
          {me.user.role === "admin" && (
            <p className="mt-4 text-sm text-muted">
              Then invite your team on the{" "}
              <Link to="/people" className="text-accent-ink hover:underline">
                People
              </Link>{" "}
              page. Each person installs the collector with their own token.
            </p>
          )}
        </div>
        <ol className="space-y-4 self-center text-sm">
          {[
            ["Create a token", "One per person. It is how every session gets a human owner."],
            ["Run one command", "Installs from this server. No PyPI, no internet needed."],
            ["Start Claude Code", "The session appears here live. Nothing else to configure."],
          ].map(([t, d], i) => (
            <li key={t} className="flex gap-3">
              <span className="tabular flex size-6 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-semibold text-bg">
                {i + 1}
              </span>
              <span>
                <span className="block font-medium">{t}</span>
                <span className="block text-muted">{d}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}
