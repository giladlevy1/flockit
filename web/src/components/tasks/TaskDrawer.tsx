import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Ban, CheckCheck, ExternalLink, GitBranch, Play, RotateCcw, Terminal, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { api } from "../../lib/api";
import { dateTime, relativeTime, taskHref, taskLabel } from "../../lib/format";
import type { Me, Task } from "../../lib/types";
import { Markdown } from "../Markdown";
import { Button, ErrorNote, Spinner } from "../ui";
import { PROFILE_TEXT, PersonChip, TaskStatus, money } from "../work";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-3 border-b border-line py-2.5 text-sm last:border-b-0">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

const TRIGGER: Record<string, string> = {
  manual: "Run by hand",
  assigned: "Assigned directly",
  schedule: "On a schedule",
  webhook: "From a webhook",
  retry: "Retry",
};

export function TaskDrawer({ id, me, onClose }: { id: string; me: Me; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: t, isLoading, error } = useQuery({
    queryKey: ["task", id],
    queryFn: () => api<Task>(`/api/tasks/${id}`),
    refetchInterval: (q) => (q.state.data && ["succeeded", "failed", "cancelled", "declined"].includes(q.state.data.status) ? 15000 : 3000),
  });
  const [showPrompt, setShowPrompt] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = useMutation({
    mutationFn: ({ action, body }: { action: string; body?: unknown }) =>
      api<Task>(`/api/tasks/${id}/${action}`, { method: "POST", json: body ?? {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["task", id] });
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
  });

  const mine = t?.assignee?.id === me.user.id;
  const active = t && ["offered", "queued", "starting", "running"].includes(t.status);
  const done = t && ["succeeded", "failed", "cancelled", "declined"].includes(t.status);

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/10 lg:hidden" onClick={onClose} />
      <aside className="drawer-in fixed top-0 right-0 bottom-0 z-40 flex w-full max-w-[520px] flex-col border-l border-line bg-surface shadow-2xl" aria-label="Task">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">Task</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && <Spinner />}
          {error && <p className="text-sm text-bad">This task is not visible to you.</p>}
          {t && (
            <>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-lg leading-snug font-semibold tracking-tight">{t.title}</h3>
                <TaskStatus status={t.status} forMe={mine} />
              </div>
              <div className="mt-1 text-sm text-muted">
                {TRIGGER[t.trigger] ?? t.trigger}
                {t.workflow && (
                  <>
                    {" · "}
                    <Link to={`/workflows?open=${t.workflow.id}`} className="text-accent-ink hover:underline">
                      {t.workflow.name}
                    </Link>
                  </>
                )}
                {" · "}
                {relativeTime(t.created_at)}
              </div>

              {mine && t.status === "offered" && (
                <div className="mt-4 rounded-xl border border-accent/30 bg-accent-soft p-4">
                  <p className="text-sm font-medium text-ink">This task is waiting for you.</p>
                  <p className="mt-1 text-sm text-ink-2">
                    Accept it to open Claude Code in a terminal on your machine, already working on it in a fresh branch. Or let
                    it run in the background and review the result.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button variant="primary" onClick={() => act.mutate({ action: "accept", body: { interactive: true } })} loading={act.isPending}>
                      <Terminal className="size-4" /> Accept and open
                    </Button>
                    <Button onClick={() => act.mutate({ action: "accept", body: { interactive: false } })}>
                      <Play className="size-4" /> Run in background
                    </Button>
                    <Button variant="ghost" onClick={() => act.mutate({ action: "decline", body: {} })}>
                      Decline
                    </Button>
                  </div>
                </div>
              )}

              {t.pr_url && (
                <a
                  href={t.pr_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-4 flex items-center gap-2 rounded-xl border border-live/30 bg-live-soft px-4 py-3 text-sm font-medium text-live hover:brightness-105"
                >
                  <GitBranch className="size-4" /> Pull request ready for review
                  <ArrowUpRight className="ml-auto size-4" />
                </a>
              )}

              {t.error && (
                <div className="mt-4 rounded-xl bg-bad-soft px-4 py-3 text-sm text-bad">
                  <div className="mb-1 font-medium">{t.status === "declined" ? "Declined" : "What went wrong"}</div>
                  <pre className="font-sans whitespace-pre-wrap">{t.error}</pre>
                </div>
              )}

              {t.result && (
                <div className="mt-4 rounded-xl border border-line p-4">
                  <div className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">Result</div>
                  <Markdown text={t.result} />
                </div>
              )}

              <dl className="mt-4">
                <Row label="Assignee">
                  <PersonChip person={t.assignee} />
                </Row>
                <Row label="Requested by">{t.triggered_by ? <PersonChip person={t.triggered_by} size={20} /> : <span className="text-muted">Flockit ({t.trigger})</span>}</Row>
                <Row label="Repository">
                  <span className="font-mono text-[13px]">{t.repo ?? "—"}</span>
                </Row>
                <Row label="Branch">
                  <span className="font-mono text-[13px]">{t.branch ?? "—"}</span>
                  {t.base_branch && <span className="text-muted"> from {t.base_branch}</span>}
                </Row>
                {t.task_ref && (
                  <Row label="Ticket">
                    {taskHref(t.task_ref) ? (
                      <a href={t.task_ref} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-accent-ink hover:underline">
                        {taskLabel(t.task_ref)} <ExternalLink className="size-3" />
                      </a>
                    ) : (
                      <span className="font-mono">{t.task_ref}</span>
                    )}
                  </Row>
                )}
                <Row label="Runs">
                  {t.assignee?.kind === "ai" ? "In a runner sandbox" : t.interactive ? "Interactive, in a terminal" : "In the background"}
                  {t.machine && <span className="text-muted"> · on {t.machine.name}</span>}
                </Row>
                <Row label="Permissions">{PROFILE_TEXT[t.permission_profile].label}</Row>
                <Row label="Timeline">
                  <ol className="space-y-0.5 text-[13px]">
                    <li>Created {dateTime(t.created_at)}</li>
                    {t.accepted_at && <li>Accepted {dateTime(t.accepted_at)}</li>}
                    {t.started_at && <li>Started {dateTime(t.started_at)}</li>}
                    {t.ended_at && <li>Finished {dateTime(t.ended_at)}</li>}
                  </ol>
                </Row>
                {t.cost_usd != null && <Row label="Model cost">{money(t.cost_usd)}</Row>}
              </dl>

              {t.session_id && (
                <Link
                  to={`/sessions/${t.session_id}`}
                  className="mt-4 flex items-center justify-between rounded-xl border border-line px-4 py-3 text-sm hover:bg-surface-2"
                >
                  <span>
                    <span className="block font-medium">Open the session</span>
                    <span className="block text-xs text-muted">Every prompt, tool call and file the agent touched</span>
                  </span>
                  <ArrowUpRight className="size-4 text-muted" />
                </Link>
              )}

              <div className="mt-5">
                <button onClick={() => setShowPrompt((s) => !s)} className="text-xs font-medium tracking-wide text-muted uppercase hover:text-ink">
                  {showPrompt ? "Hide" : "Show"} prompt
                </button>
                {showPrompt && <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[12.5px] whitespace-pre-wrap">{t.prompt}</pre>}
              </div>

              <ErrorNote error={act.error} />
              <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
                {mine && active && t.status !== "offered" && t.interactive && (
                  <Button onClick={() => act.mutate({ action: "complete" })}>
                    <CheckCheck className="size-4" /> Mark done
                  </Button>
                )}
                {active && (
                  <Button variant="danger" onClick={() => confirm("Cancel this task? A running agent is stopped.") && act.mutate({ action: "cancel" })}>
                    <Ban className="size-4" /> Cancel
                  </Button>
                )}
                {done && (
                  <Button onClick={() => act.mutate({ action: "retry" })}>
                    <RotateCcw className="size-4" /> Run again
                  </Button>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
