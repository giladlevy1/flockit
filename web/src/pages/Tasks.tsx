import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Laptop, Plus, Search, Terminal, WifiOff } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { NewTaskDialog } from "../components/tasks/NewTaskDialog";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { Button, Card, PageHeader, Spinner } from "../components/ui";
import { PersonChip, TaskStatus, statusLabel } from "../components/work";
import { api, qs } from "../lib/api";
import { relativeTime, shortRepo } from "../lib/format";
import type { DispatchMode, Inbox, Me, RunStatus, Task, TaskPage } from "../lib/types";

const FILTERS: { key: string; label: string; statuses: RunStatus[] }[] = [
  { key: "open", label: "Open", statuses: ["offered", "queued", "starting", "running"] },
  { key: "running", label: "Running", statuses: ["starting", "running"] },
  { key: "done", label: "Done", statuses: ["succeeded"] },
  { key: "failed", label: "Failed", statuses: ["failed"] },
  { key: "all", label: "All", statuses: [] },
];

export function TasksPage({ me }: { me: Me }) {
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") ?? (me.user.role === "developer" ? "mine" : "all")) as "mine" | "all";
  const filter = FILTERS.find((f) => f.key === params.get("status")) ?? FILTERS[0];
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const selected = params.get("task");

  const set = (key: string, value: string | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    });

  const tasks = useQuery({
    queryKey: ["tasks", view, filter.key, q],
    queryFn: () => api<TaskPage>(`/api/tasks${qs({ view, status: filter.statuses, q: q || undefined, limit: 200 })}`),
    refetchInterval: 4000,
    placeholderData: keepPreviousData,
  });
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<Inbox>("/api/tasks/inbox"), refetchInterval: 5000 });
  const counts = tasks.data?.counts ?? {};
  const countFor = (f: (typeof FILTERS)[number]) =>
    f.statuses.length ? f.statuses.reduce((n, s) => n + (counts[s] ?? 0), 0) : Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);

  return (
    <div>
      <PageHeader
        title="Tasks"
        sub="Work handed to people and AI developers: by hand, from a workflow, on a schedule or from a webhook."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus className="size-4" /> New task
          </Button>
        }
      />

      {inbox.data && <MachineBar inbox={inbox.data} />}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5">
          {(["mine", "all"] as const).map((v) => (
            <button
              key={v}
              onClick={() => set("view", v)}
              className={clsx("rounded-md px-3 py-1.5 text-[13px]", view === v ? "bg-ink font-medium text-bg" : "text-muted hover:text-ink")}
            >
              {v === "mine" ? (
                <>
                  Assigned to me
                  {inbox.data && inbox.data.offered > 0 && (
                    <span className="ml-1.5 rounded-full bg-accent px-1.5 py-px text-[11px] font-semibold text-white">{inbox.data.offered}</span>
                  )}
                </>
              ) : me.scope === "organisation" ? (
                "All tasks"
              ) : me.scope === "team" ? (
                "My teams"
              ) : (
                "Mine and delegated"
              )}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => set("status", f.key === "open" ? null : f.key)}
              className={clsx(
                "rounded-lg border px-2.5 py-1 text-[13px]",
                filter.key === f.key ? "border-accent/40 bg-accent-soft font-medium text-accent-ink" : "border-line bg-surface text-ink-2 hover:bg-surface-2",
              )}
            >
              {f.label} <span className="tabular text-muted">{countFor(f)}</span>
            </button>
          ))}
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search tasks"
              aria-label="Search tasks"
              className="h-8 w-44 rounded-lg border border-line bg-surface pr-2 pl-8 text-[13px] focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      </div>

      <Card className="mt-3 overflow-hidden">
        {tasks.isLoading ? (
          <div className="flex h-40 items-center justify-center text-muted">
            <Spinner />
          </div>
        ) : tasks.data && tasks.data.items.length ? (
          <ul className="divide-y divide-line">
            {tasks.data.items.map((t) => (
              <TaskRow key={t.id} t={t} me={me} selected={selected === t.id} onOpen={() => set("task", t.id)} />
            ))}
          </ul>
        ) : (
          <EmptyTasks view={view} onCreate={() => setCreating(true)} />
        )}
      </Card>

      {creating && <NewTaskDialog me={me} open onClose={() => setCreating(false)} />}
      {selected && <TaskDrawer id={selected} me={me} onClose={() => set("task", null)} />}
    </div>
  );
}

function TaskRow({ t, me, selected, onOpen }: { t: Task; me: Me; selected: boolean; onOpen: () => void }) {
  const qc = useQueryClient();
  const accept = useMutation({
    mutationFn: (interactive: boolean) => api(`/api/tasks/${t.id}/accept`, { method: "POST", json: { interactive } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
  });
  const mine = t.assignee?.id === me.user.id;
  return (
    <li
      onClick={onOpen}
      className={clsx("flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors", selected ? "bg-accent-soft/60" : "hover:bg-surface-2/70")}
    >
      <div className="w-[190px] shrink-0">
        <PersonChip person={t.assignee} sub={t.machine ? `on ${t.machine.name}` : t.assignee?.kind === "ai" ? "AI developer" : undefined} />
      </div>
      <div className="min-w-0 flex-1 basis-64">
        <div className="truncate font-medium text-ink">{t.title}</div>
        <div className="truncate text-xs text-muted">
          <span className="font-mono">{shortRepo(t.repo) || "no repo"}</span>
          {t.workflow ? ` · ${t.workflow.name}` : t.triggered_by && t.triggered_by.id !== t.assignee?.id ? ` · from ${t.triggered_by.name}` : ""}
          {" · "}
          {relativeTime(t.created_at)}
        </div>
      </div>
      {t.pr_url && (
        <a href={t.pr_url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} className="text-[13px] text-accent-ink hover:underline">
          Pull request
        </a>
      )}
      {mine && t.status === "offered" ? (
        <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="primary" onClick={() => accept.mutate(true)} loading={accept.isPending}>
            <Terminal className="size-3.5" /> Accept
          </Button>
          <Button size="sm" onClick={() => accept.mutate(false)} title="Run it in the background and review the result">
            Background
          </Button>
        </div>
      ) : (
        <span title={statusLabel(t.status, mine)}>
          <TaskStatus status={t.status} forMe={mine} />
        </span>
      )}
    </li>
  );
}

function EmptyTasks({ view, onCreate }: { view: string; onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      <p className="font-medium">{view === "mine" ? "Nothing assigned to you" : "No tasks here yet"}</p>
      <p className="max-w-md text-sm text-muted">
        Hand work to a person or an AI developer. It starts as a Claude Code session on their machine or in a sandbox, and every
        step is recorded here.{" "}
        <Link to="/workflows" className="text-accent-ink hover:underline">
          Workflows
        </Link>{" "}
        create tasks automatically.
      </p>
      <Button size="sm" className="mt-2" onClick={onCreate}>
        <Plus className="size-3.5" /> New task
      </Button>
    </div>
  );
}

function MachineBar({ inbox }: { inbox: Inbox }) {
  const qc = useQueryClient();
  const online = inbox.machines.filter((m) => m.online);
  const setMode = useMutation({
    mutationFn: (mode: DispatchMode) => api("/api/auth/me", { method: "PATCH", json: { dispatch_mode: mode } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const modes: { value: DispatchMode; label: string; hint: string }[] = [
    { value: "ask", label: "Ask me", hint: "Tasks wait for you to accept" },
    { value: "auto", label: "Auto-start", hint: "Workflows set to auto-start run in the background" },
    { value: "off", label: "Paused", hint: "Nothing starts on your machine" },
  ];
  return (
    <Card className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
      <div className="flex items-center gap-2.5 text-sm">
        {online.length ? (
          <>
            <span className="flex size-8 items-center justify-center rounded-lg bg-live-soft text-live">
              <Laptop className="size-4" />
            </span>
            <span>
              <span className="block font-medium">{online.map((m) => m.name).join(", ")} ready</span>
              <span className="block text-xs text-muted">Tasks you accept open in Claude Code there</span>
            </span>
          </>
        ) : (
          <>
            <span className="flex size-8 items-center justify-center rounded-lg bg-warn-soft text-warn">
              <WifiOff className="size-4" />
            </span>
            <span>
              <span className="block font-medium">{inbox.machines.length ? "Your machine is offline" : "No machine connected"}</span>
              <span className="block text-xs text-muted">
                Tasks wait until the Flockit agent runs.{" "}
                <Link to="/connect" className="text-accent-ink hover:underline">
                  {inbox.machines.length ? "Check the agent" : "Connect Claude Code"}
                </Link>
              </span>
            </span>
          </>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2 text-sm">
        <span className="text-muted">Tasks on my machine:</span>
        <div className="inline-flex rounded-lg border border-line p-0.5">
          {modes.map((m) => (
            <button
              key={m.value}
              title={m.hint}
              onClick={() => setMode.mutate(m.value)}
              className={clsx("rounded-md px-2.5 py-1 text-[13px]", inbox.dispatch_mode === m.value ? "bg-ink font-medium text-bg" : "text-muted hover:text-ink")}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}
