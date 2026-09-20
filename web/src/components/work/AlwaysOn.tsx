import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Laptop, MoonStar } from "lucide-react";
import { Link } from "react-router";

import { api } from "../../lib/api";
import type { Continuity } from "../../lib/types";
import { Badge, Button, Card, ErrorNote } from "../ui";

/**
 * Always-on sessions, in one switch.
 *
 * The promise is small enough to say in a sentence and big enough to be the reason people
 * keep Flockit installed: close your laptop mid-task and the work does not stop — your own
 * AI developer picks it up from exactly where you left off.
 */
export function AlwaysOn({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient();
  const state = useQuery({ queryKey: ["continuity"], queryFn: () => api<Continuity>("/api/me/continuity") });
  const set = useMutation({
    mutationFn: (enabled: boolean) => api<Continuity>("/api/me/continuity", { method: "PUT", json: { enabled } }),
    onSuccess: (next) => {
      qc.setQueryData(["continuity"], next);
      qc.invalidateQueries({ queryKey: ["ai-developers"] });
    },
  });

  const on = state.data?.enabled ?? false;
  const agent = state.data?.agent;
  const noRunner = (state.data?.runners ?? 0) === 0;

  return (
    <Card className={compact ? "p-4" : "p-5"}>
      <div className="flex items-start gap-3">
        <span className={on ? "mt-0.5 inline-flex size-8 items-center justify-center rounded-lg bg-accent-soft text-accent" : "mt-0.5 inline-flex size-8 items-center justify-center rounded-lg bg-surface-2 text-muted"}>
          <MoonStar className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">Always-on sessions</h2>
            {on && <Badge tone="accent">on</Badge>}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
            Close your laptop in the middle of a task and the work carries on:{" "}
            {agent ? <span className="font-medium">{agent.name}</span> : "your own AI developer"} picks the session up in
            the cloud, from your working tree as you left it — uncommitted changes included.
          </p>

          {on ? (
            <div className="mt-3 space-y-2">
              <p className="flex items-center gap-2 text-[13px] text-muted">
                <Check className="size-3.5 text-live" /> A snapshot of your work is kept continuable while you code.
              </p>
              {noRunner && (
                <p className="flex items-start gap-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-ink">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" />
                  <span>
                    No runner is set up yet, so there is nowhere for the work to continue.{" "}
                    <Link to="/ai" className="text-accent-ink hover:underline">
                      Add one
                    </Link>
                    .
                  </span>
                </p>
              )}
              {state.data?.last_handover && (
                <p className="text-[13px] text-muted">
                  Last continued: <span className="text-ink">{state.data.last_handover.title}</span> (
                  {state.data.last_handover.status})
                </p>
              )}
              <Button size="sm" variant="ghost" loading={set.isPending} onClick={() => set.mutate(false)}>
                Turn off
              </Button>
            </div>
          ) : (
            <div className="mt-3">
              <Button size="sm" variant="primary" loading={set.isPending} onClick={() => set.mutate(true)}>
                <Laptop className="size-3.5" /> Turn it on
              </Button>
              <p className="mt-2 text-xs text-muted">
                Creates one AI developer that is yours alone. It only ever continues your own sessions, and everything it
                does is recorded here like any other session.
              </p>
            </div>
          )}
          <ErrorNote error={set.error} />
        </div>
      </div>
    </Card>
  );
}
