import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Inbox as InboxIcon, Laptop, Play, Radio } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "../../lib/api";
import type { Inbox, Me, TaskPage } from "../../lib/types";
import { TaskDrawer } from "../tasks/TaskDrawer";
import { Button, Card } from "../ui";

/**
 * The only thing allowed above the session list: work waiting on *this person*.
 *
 * It renders nothing at all when there is nothing to decide, which is most days — that is
 * the point. A task offered to you can be started or declined right here, because making
 * someone open a second page to say yes is how inboxes die.
 */
export function Attention({ me }: { me: Me }) {
  const [open, setOpen] = useState<string | null>(null);
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<Inbox>("/api/tasks/inbox"), refetchInterval: 10_000 });
  const mine = useQuery({
    queryKey: ["tasks", "attention"],
    queryFn: () => api<TaskPage>("/api/tasks?view=mine&status=offered&status=running&status=starting&limit=6"),
    refetchInterval: 10_000,
  });

  const items = mine.data?.items ?? [];
  const offered = items.filter((t) => t.status === "offered");
  const running = items.filter((t) => t.status !== "offered");
  const machine = (inbox.data?.machines ?? []).find((m) => m.online);
  if (!items.length) return null;

  return (
    <>
      <Card className="mb-6 overflow-hidden border-accent/40">
        <div className="flex items-center gap-2 border-b border-line bg-accent-soft/40 px-4 py-2.5">
          <InboxIcon className="size-4 text-accent" />
          <h2 className="text-sm font-semibold">
            {offered.length > 0
              ? `${offered.length} task${offered.length > 1 ? "s" : ""} waiting for you`
              : `${running.length} task${running.length > 1 ? "s" : ""} in progress`}
          </h2>
          <Link to="/tasks" className="ml-auto text-[13px] text-accent-ink hover:underline">
            All tasks
          </Link>
        </div>
        <ul className="divide-y divide-line">
          {[...offered, ...running].map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <button onClick={() => setOpen(t.id)} className="min-w-0 flex-1 text-left">
                <span className="flex items-center gap-2">
                  {t.status !== "offered" && <Radio className="size-3.5 shrink-0 animate-pulse text-live" />}
                  <span className="truncate text-sm font-medium">{t.title}</span>
                </span>
                <span className="mt-0.5 block truncate text-xs text-muted">
                  {t.repo ?? "no repository"}
                  {t.triggered_by ? ` · from ${t.triggered_by.name}` : ""}
                  {t.workflow ? ` · ${t.workflow.name}` : ""}
                </span>
              </button>
              {t.status === "offered" ? (
                <Decide id={t.id} canRun={!!machine} onOpen={() => setOpen(t.id)} />
              ) : t.session_id ? (
                <Link to={`/sessions/${t.session_id}`}>
                  <Button size="sm" variant="secondary">
                    Watch <ArrowRight className="size-3.5" />
                  </Button>
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
        {offered.length > 0 && !machine && (
          <p className="flex items-center gap-2 border-t border-line bg-surface-2 px-4 py-2 text-xs text-muted">
            <Laptop className="size-3.5" /> No machine of yours is online, so this can only start once one is.{" "}
            <Link to="/connect" className="text-accent-ink hover:underline">
              Connect one
            </Link>
          </p>
        )}
      </Card>
      {open && <TaskDrawer id={open} me={me} onClose={() => setOpen(null)} />}
    </>
  );
}

function Decide({ id, canRun, onOpen }: { id: string; canRun: boolean; onOpen: () => void }) {
  const qc = useQueryClient();
  const accept = useMutation({
    mutationFn: () => api(`/api/tasks/${id}/accept`, { method: "POST", json: { interactive: true } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
  });
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" variant="ghost" onClick={onOpen}>
        Read it
      </Button>
      <Button size="sm" variant="primary" loading={accept.isPending} disabled={!canRun} onClick={() => accept.mutate()}>
        <Play className="size-3.5" /> Start here
      </Button>
    </div>
  );
}
