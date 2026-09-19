import { useQuery } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { api } from "../../lib/api";
import { dateTime, duration, prettyModel, taskHref, vendorLabel } from "../../lib/format";
import type { Session } from "../../lib/types";
import { Avatar, Badge, Spinner } from "../ui";
import { liveDuration } from "./SessionTable";
import { StatusBadge } from "./StatusBadge";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 border-b border-line py-2.5 text-sm last:border-b-0">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{children}</dd>
    </div>
  );
}

function FilterLink({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className="rounded-md border border-line px-2 py-1 text-xs text-ink-2 hover:bg-surface-2 hover:text-ink">
      {children}
    </button>
  );
}

export function SessionDrawer({
  id,
  now,
  onClose,
  onFilter,
}: {
  id: string;
  now: number;
  onClose: () => void;
  onFilter: (key: "owner" | "repo" | "model" | "task_ref", value: string) => void;
}) {
  const { data: s, isLoading, error } = useQuery({
    queryKey: ["session", id],
    queryFn: () => api<Session>(`/api/sessions/${id}`),
    refetchInterval: 5000,
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/10 lg:hidden" onClick={onClose} />
      <aside
        className="drawer-in fixed top-0 right-0 bottom-0 z-40 flex w-full max-w-[440px] flex-col border-l border-line bg-surface shadow-2xl"
        aria-label="Session details"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">Session</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && <Spinner />}
          {error && <p className="text-sm text-bad">This session is not visible to you.</p>}
          {s && (
            <>
              <div className="mb-5 flex items-center gap-3">
                <Avatar name={s.owner.name} id={s.owner.id} size={40} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{s.owner.name}</div>
                  <div className="truncate text-sm text-muted">{s.owner.email}</div>
                </div>
                <StatusBadge s={s} />
              </div>

              <div className="mb-5 grid grid-cols-3 gap-2">
                <Stat label="Duration" value={duration(liveDuration(s, now))} />
                <Stat label="Turns" value={String(s.turn_count)} />
                <Stat label="Models" value={String(Math.max(1, s.models_used.length))} />
              </div>

              <dl>
                <Row label="Origin">
                  {s.origin === "workflow" ? <Badge tone="accent">Workflow</Badge> : "Started by a person"}
                </Row>
                <Row label="Agent">
                  {vendorLabel(s.agent_vendor)}
                  {s.agent_version && <span className="text-muted"> {s.agent_version}</span>}
                </Row>
                <Row label="Model">
                  {s.models_used.length > 1 ? (
                    <div className="flex flex-wrap gap-1">
                      {s.models_used.map((m) => (
                        <Badge key={m}>{prettyModel(m)}</Badge>
                      ))}
                    </div>
                  ) : (
                    <span title={s.agent_model ?? undefined}>{prettyModel(s.agent_model)}</span>
                  )}
                </Row>
                <Row label="Repo">
                  <span className="font-mono text-[13px]">{s.repo ?? "—"}</span>
                </Row>
                <Row label="Branch">
                  <span className="font-mono text-[13px]">{s.branch ?? "—"}</span>
                </Row>
                <Row label="Task">
                  {s.task_ref ? (
                    taskHref(s.task_ref) ? (
                      <a
                        href={s.task_ref}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-flex items-center gap-1 font-mono text-[13px] break-all text-accent-ink hover:underline"
                      >
                        {s.task_ref} <ExternalLink className="size-3 shrink-0" />
                      </a>
                    ) : (
                      <span className="font-mono text-[13px]">{s.task_ref}</span>
                    )
                  ) : (
                    <span className="text-muted">None detected</span>
                  )}
                </Row>
                <Row label="Started">{dateTime(s.started_at)}</Row>
                <Row label="Last activity">{dateTime(s.last_seen_at)}</Row>
                <Row label="Ended">
                  {s.ended_at ? (
                    <>
                      {dateTime(s.ended_at)}
                      {s.end_reason && <span className="text-muted"> · {s.end_reason.replaceAll("_", " ")}</span>}
                    </>
                  ) : (
                    <span className="text-muted">Still open</span>
                  )}
                </Row>
              </dl>

              <div className="mt-6">
                <div className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">Show all sessions for</div>
                <div className="flex flex-wrap gap-1.5">
                  <FilterLink onClick={() => onFilter("owner", s.owner.id)}>{s.owner.name}</FilterLink>
                  {s.repo && <FilterLink onClick={() => onFilter("repo", s.repo!)}>this repo</FilterLink>}
                  {s.task_ref && <FilterLink onClick={() => onFilter("task_ref", s.task_ref!)}>this task</FilterLink>}
                  {s.agent_model && <FilterLink onClick={() => onFilter("model", s.agent_model!)}>{prettyModel(s.agent_model)}</FilterLink>}
                </div>
              </div>

              <p className="mt-8 rounded-lg bg-surface-2 px-3 py-2.5 text-xs leading-relaxed text-muted">
                Flockit records session metadata only. Prompts, responses, code and command output never leave the
                developer's machine.
              </p>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-2 px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="tabular text-[15px] font-semibold">{value}</div>
    </div>
  );
}
