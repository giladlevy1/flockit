import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Database, ExternalLink, FolderGit2, Plus, Workflow as WorkflowIcon } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { NewTaskDialog } from "../components/tasks/NewTaskDialog";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { Badge, Button, Card, PageHeader, Spinner } from "../components/ui";
import { BotAvatar, TaskStatus, money } from "../components/work";
import { api } from "../lib/api";
import { prettyModel, relativeTime } from "../lib/format";
import type { AiDeveloperProfile, Me } from "../lib/types";

/**
 * One AI developer, in the terms you would use for a colleague: what it has been working
 * on, what it knows its way around, and what it works *against* — because an agent with a
 * database that looks like production can test its own change before anyone reviews it.
 */
export function AiDeveloperPage({ me }: { me: Me }) {
  const { id = "" } = useParams();
  const [task, setTask] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const profile = useQuery({
    queryKey: ["ai-developer", id],
    queryFn: () => api<AiDeveloperProfile>(`/api/ai-developers/${id}`),
    refetchInterval: 5000,
  });

  if (profile.isLoading) return <Spinner />;
  if (!profile.data) return <p className="text-muted">This AI developer does not exist, or you cannot see it.</p>;

  const { developer: d, expertise, tasks, sessions, workflows } = profile.data;
  const env = d.environment;
  const done = d.stats.tasks.succeeded ?? 0;
  const failed = d.stats.tasks.failed ?? 0;

  return (
    <div>
      <Link to="/ai" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> AI developers
      </Link>
      <div className="mb-4 flex items-center gap-3">
        <BotAvatar id={d.id} size={44} />
        <div className="min-w-0 flex-1">
          <PageHeader
            title={d.name}
            sub={
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>{d.agent_vendor === "codex" ? "Codex" : "Claude Code"}</span>
                <span>· {d.agent_model ? prettyModel(d.agent_model) : "default model"}</span>
                {d.default_repo && <span>· {d.default_repo}</span>}
                {d.sponsor && <span>· sponsored by {d.sponsor.name}</span>}
                {!d.is_active && <Badge>Retired</Badge>}
              </span>
            }
            actions={
              <Button variant="primary" onClick={() => setAssigning(true)}>
                <Plus className="size-4" /> Assign a task
              </Button>
            }
          />
        </div>
      </div>

      {d.current_task && (
        <Card className="mb-4 flex flex-wrap items-center gap-3 border-live/40 px-4 py-3">
          <span className="flex size-2 animate-pulse rounded-full bg-live" />
          <span className="min-w-0 flex-1 truncate text-sm">
            Working on <span className="font-medium">{d.current_task.title}</span>
          </span>
          <button onClick={() => setTask(d.current_task!.id)} className="text-[13px] text-accent-ink hover:underline">
            Open
          </button>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <Card className="overflow-hidden">
            <h2 className="border-b border-line px-4 py-2.5 text-sm font-semibold">Recent tasks</h2>
            {tasks.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted">
                Nothing yet. Give it a real ticket — it works in a sandbox, so the worst case is a branch you delete.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {tasks.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                    <button onClick={() => setTask(t.id)} className="min-w-0 flex-1 text-left">
                      <span className="block truncate text-sm font-medium">{t.title}</span>
                      <span className="block truncate text-xs text-muted">
                        {t.repo ?? "no repo"} · {relativeTime(t.created_at)}
                        {t.cost_usd ? ` · ${money(t.cost_usd)}` : ""}
                      </span>
                    </button>
                    <TaskStatus status={t.status} />
                    {t.pr_url && (
                      <a
                        href={t.pr_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-muted hover:text-ink"
                        aria-label="Pull request"
                      >
                        <ExternalLink className="size-4" />
                      </a>
                    )}
                    {t.session_id && (
                      <Link to={`/sessions/${t.session_id}`} className="text-[13px] text-accent-ink hover:underline">
                        Session
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="overflow-hidden">
            <h2 className="border-b border-line px-4 py-2.5 text-sm font-semibold">Sessions</h2>
            {sessions.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted">No sessions yet.</p>
            ) : (
              <ul className="divide-y divide-line">
                {sessions.map((s) => (
                  <li key={s.id}>
                    <Link to={`/sessions/${s.id}`} className="flex flex-wrap items-center gap-3 px-4 py-2.5 hover:bg-surface-2">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">{s.title ?? "Untitled session"}</span>
                        <span className="block truncate text-xs text-muted">
                          {s.repo ?? "no repo"} · {relativeTime(s.started_at)}
                        </span>
                      </span>
                      <span className="tabular text-xs text-muted">
                        {s.turns} turns · {s.files_touched} files
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Workbench env={env} />

          <Card className="p-4">
            <h2 className="mb-2 text-sm font-semibold">What it knows</h2>
            {expertise.repos.length === 0 && expertise.areas.length === 0 ? (
              <p className="text-[13px] text-muted">
                Built from the work it does. After a few tasks this shows the repositories and parts of the codebase it
                has actually touched.
              </p>
            ) : (
              <div className="space-y-3">
                {expertise.repos.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs text-muted">Repositories</p>
                    <ul className="space-y-1">
                      {expertise.repos.map((r) => (
                        <li key={r.repo} className="flex items-center gap-2 text-[13px]">
                          <FolderGit2 className="size-3.5 shrink-0 text-muted" />
                          <span className="min-w-0 flex-1 truncate">{r.repo}</span>
                          <span className="tabular text-xs text-muted">{r.tasks}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {expertise.areas.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs text-muted">Areas it has edited</p>
                    <div className="flex flex-wrap gap-1.5">
                      {expertise.areas.map((a) => (
                        <Badge key={a.area}>
                          {a.area} <span className="tabular opacity-60">{a.files}</span>
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card className="p-4">
            <h2 className="mb-2 text-sm font-semibold">Record</h2>
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-muted">Succeeded</dt>
              <dd className="tabular text-right">{done}</dd>
              <dt className="text-muted">Failed</dt>
              <dd className="tabular text-right">{failed}</dd>
              <dt className="text-muted">Spend</dt>
              <dd className="tabular text-right">{money(d.stats.cost_usd)}</dd>
            </dl>
          </Card>

          <Card className="overflow-hidden">
            <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <WorkflowIcon className="size-4 text-muted" />
              <h2 className="text-sm font-semibold">Workflows pointed at it</h2>
            </div>
            {workflows.length === 0 ? (
              <p className="px-4 py-4 text-[13px] text-muted">
                None.{" "}
                <Link to="/workflows" className="text-accent-ink hover:underline">
                  Create one
                </Link>{" "}
                to send it work on a schedule, or whenever a ticket is filed.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {workflows.map((w) => (
                  <li key={w.id}>
                    <Link to={`/workflows?workflow=${w.id}`} className="flex items-center gap-2 px-4 py-2.5 hover:bg-surface-2">
                      <span className="min-w-0 flex-1 truncate text-[13px]">{w.name}</span>
                      <Badge tone={w.enabled ? "accent" : "neutral"}>{w.schedule_cron ?? w.trigger}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {d.instructions && (
            <Card className="p-4">
              <h2 className="mb-2 text-sm font-semibold">Standing instructions</h2>
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">{d.instructions}</p>
            </Card>
          )}
        </div>
      </div>

      {task && <TaskDrawer id={task} me={me} onClose={() => setTask(null)} />}
      <NewTaskDialog
        me={me}
        open={assigning}
        onClose={() => setAssigning(false)}
        initial={{ assignee_id: d.id, repo: d.default_repo ?? "" }}
      />
    </div>
  );
}

function Workbench({ env }: { env: AiDeveloperProfile["developer"]["environment"] }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <Database className="size-4 text-muted" />
        <h2 className="text-sm font-semibold">Workbench</h2>
        {env && <Badge tone={env.persistent ? "accent" : "neutral"}>{env.persistent ? "kept between tasks" : "fresh each task"}</Badge>}
      </div>
      {!env ? (
        <p className="px-4 py-4 text-[13px] leading-relaxed text-muted">
          None yet. Give it a database and it can migrate, seed and query while it works — then run the tests against
          something that behaves like production instead of guessing.
        </p>
      ) : (
        <div className="space-y-3 p-4">
          <div>
            <p className="text-[13px] font-medium">{env.name}</p>
            {env.description && <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{env.description}</p>}
          </div>
          {env.services.length > 0 && (
            <ul className="space-y-1.5">
              {env.services.map((s) => (
                <li key={s.name} className="flex items-baseline gap-2 text-[13px]">
                  <span className="font-mono text-xs text-accent-ink">{s.name}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{s.image}</span>
                  {s.url_env && <span className="shrink-0 font-mono text-[11px] text-muted">${s.url_env}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
