import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Cpu, Laptop, Plug, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { api } from "../../lib/api";
import type { AiDeveloper, Inbox, Me, TaskPage } from "../../lib/types";
import { Button, Card } from "../ui";
import { NewAiDeveloper } from "./NewAiDeveloper";

/**
 * The first thing a new person sees. Three steps, in the order that pays off fastest:
 * connect this machine, hire an AI developer, give it something to do. Each step knows
 * whether it is already done, so this doubles as a status panel until it is dismissed.
 */
export function GettingStarted({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [hiring, setHiring] = useState(false);
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<Inbox>("/api/tasks/inbox") });
  const devs = useQuery({ queryKey: ["ai-developers"], queryFn: () => api<AiDeveloper[]>("/api/ai-developers") });
  const tasks = useQuery({ queryKey: ["tasks", "any"], queryFn: () => api<TaskPage>("/api/tasks?limit=1") });

  const dismiss = useMutation({
    mutationFn: () => api("/api/auth/me", { method: "PATCH", json: { onboarded: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });

  const connected = (inbox.data?.machines ?? []).length > 0;
  const hired = (devs.data ?? []).length > 0;
  const gaveWork = (tasks.data?.total ?? 0) > 0;
  const canHire = me.user.role === "admin";

  const steps: { done: boolean; icon: ReactNode; title: string; body: string; action: ReactNode }[] = [
    {
      done: connected,
      icon: <Laptop className="size-4" />,
      title: "Connect this machine",
      body: connected
        ? "Your Claude Code sessions are being captured, and tasks can start here."
        : "One command. Your sessions appear here as you work, and work can be sent to you.",
      action: connected ? null : (
        <Link to="/connect">
          <Button size="sm" variant="primary">
            Get the command <ArrowRight className="size-3.5" />
          </Button>
        </Link>
      ),
    },
    {
      done: hired,
      icon: <Cpu className="size-4" />,
      title: "Hire your first AI developer",
      body: hired
        ? "It works in its own sandbox, with its own workbench, and everything it does is recorded here."
        : "A teammate that takes tasks, works in a sandbox with a real database, and opens pull requests.",
      action: hired ? null : canHire ? (
        <Button size="sm" variant="primary" onClick={() => setHiring(true)}>
          <Sparkles className="size-3.5" /> Hire one
        </Button>
      ) : (
        <span className="text-xs text-muted">An admin creates these.</span>
      ),
    },
    {
      done: gaveWork,
      icon: <Plug className="size-4" />,
      title: "Give it something to do",
      body: gaveWork
        ? "Follow it live below: every prompt, command and file it touches."
        : "A real ticket works best. You will see it work, step by step, and get a pull request at the end.",
      action: gaveWork ? null : hired ? (
        <Link to="/ai">
          <Button size="sm" variant="primary">
            Assign a task <ArrowRight className="size-3.5" />
          </Button>
        </Link>
      ) : null,
    },
  ];
  const done = steps.filter((s) => s.done).length;

  return (
    <>
      <Card className="mb-6 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Get started</h2>
            <p className="text-xs text-muted">
              {done === steps.length
                ? "All set. This panel is only here until you dismiss it."
                : `${done} of ${steps.length} done — about two minutes.`}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => dismiss.mutate()} loading={dismiss.isPending}>
            Dismiss
          </Button>
        </div>
        <ol className="grid gap-px bg-line sm:grid-cols-3">
          {steps.map((step) => (
            <li key={step.title} className="flex min-w-0 flex-col gap-2 bg-surface p-4">
              <div className="flex items-center gap-2">
                <span
                  className={
                    step.done
                      ? "inline-flex size-7 items-center justify-center rounded-lg bg-live-soft text-live"
                      : "inline-flex size-7 items-center justify-center rounded-lg bg-accent-soft text-accent"
                  }
                >
                  {step.done ? <Check className="size-4" /> : step.icon}
                </span>
                <span className="text-sm font-medium">{step.title}</span>
              </div>
              <p className="text-[13px] leading-relaxed text-muted">{step.body}</p>
              {step.action && <div className="mt-auto pt-1">{step.action}</div>}
            </li>
          ))}
        </ol>
      </Card>
      <NewAiDeveloper open={hiring} onClose={() => setHiring(false)} />
    </>
  );
}
