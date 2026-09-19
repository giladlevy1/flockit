import { useInfiniteQuery } from "@tanstack/react-query";

import { Button, Card, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import type { AuditItem } from "../lib/types";

const LABELS: Record<string, string> = {
  "task.created": "created a task",
  "task.accepted": "accepted a task",
  "task.declined": "declined a task",
  "task.cancelled": "cancelled a task",
  "task.succeeded": "finished a task",
  "task.failed": "failed a task",
  "workflow.created": "created a workflow",
  "workflow.updated": "updated a workflow",
  "workflow.deleted": "deleted a workflow",
  "workflow.webhook_rotated": "rotated a webhook secret",
  "ai_developer.created": "created an AI developer",
  "ai_developer.updated": "updated an AI developer",
  "runner.created": "added a runner",
  "runner.revoked": "removed a runner",
  "user.dispatch_mode": "changed task preferences",
};

function describe(e: AuditItem): string {
  const d = e.detail ?? {};
  const name = (d.title ?? d.name) as string | undefined;
  const extra = [
    name ? `“${name}”` : null,
    d.assignee ? `for ${d.assignee}` : null,
    d.trigger && d.trigger !== "assigned" ? `(${d.trigger})` : null,
    d.mode ? `→ ${d.mode}` : null,
    d.pr_url ? String(d.pr_url) : null,
  ].filter(Boolean);
  return `${LABELS[e.action] ?? e.action} ${extra.join(" ")}`.trim();
}

export function AuditPage() {
  const log = useInfiniteQuery({
    queryKey: ["audit"],
    queryFn: ({ pageParam }) => api<{ items: AuditItem[] }>(`/api/audit?limit=100${pageParam ? `&before=${pageParam}` : ""}`),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.items.length === 100 ? last.items[last.items.length - 1].id : undefined),
  });
  const items = log.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="max-w-4xl">
      <PageHeader title="Audit log" sub="Every time work was dispatched to a person or an agent, and every change to who can do what." />
      <Card className="overflow-hidden">
        {log.isLoading ? (
          <div className="p-6">
            <Spinner />
          </div>
        ) : items.length ? (
          <ul className="divide-y divide-line">
            {items.map((e) => (
              <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-2.5 text-sm">
                <span className="tabular w-36 shrink-0 text-xs text-muted">{dateTime(e.created_at)}</span>
                <span className="font-medium">{e.actor}</span>
                <span className="min-w-0 flex-1 break-words text-ink-2">{describe(e)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-8 text-center text-sm text-muted">Nothing recorded yet.</p>
        )}
        {log.hasNextPage && (
          <div className="border-t border-line p-2 text-center">
            <Button size="sm" variant="ghost" onClick={() => log.fetchNextPage()} loading={log.isFetchingNextPage}>
              Older
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
