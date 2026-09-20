import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Cpu, Laptop, MoonStar, Server, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { api } from "../../lib/api";
import type { AiDeveloper, Continuity, Inbox, Me, Runner } from "../../lib/types";
import { Button, Card } from "../ui";
import { NewAiDeveloper } from "./NewAiDeveloper";

/**
 * The first four minutes.
 *
 * Ordered by what earns trust fastest: see your own work captured, make it impossible to
 * lose, give the agents somewhere to run, then hand one a real task. Each step knows
 * whether it is already done, so this doubles as a status panel until it is dismissed.
 */
export function GettingStarted({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [hiring, setHiring] = useState(false);
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api<Inbox>("/api/tasks/inbox") });
  const devs = useQuery({ queryKey: ["ai-developers"], queryFn: () => api<AiDeveloper[]>("/api/ai-developers") });
  const runners = useQuery({ queryKey: ["runners"], queryFn: () => api<Runner[]>("/api/runners") });
  const continuity = useQuery({ queryKey: ["continuity"], queryFn: () => api<Continuity>("/api/me/continuity") });

  const alwaysOn = useMutation({
    mutationFn: () => api<Continuity>("/api/me/continuity", { method: "PUT", json: { enabled: true } }),
    onSuccess: (next) => {
      qc.setQueryData(["continuity"], next);
      qc.invalidateQueries({ queryKey: ["ai-developers"] });
    },
  });
  const dismiss = useMutation({
    mutationFn: () => api("/api/auth/me", { method: "PATCH", json: { onboarded: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });

  const connected = (inbox.data?.machines ?? []).length > 0;
  const on = continuity.data?.enabled ?? false;
  const hasRunner = (runners.data ?? []).length > 0;
  const otherAgents = (devs.data ?? []).filter((d) => !d.name.endsWith("'s agent"));

  const steps: { done: boolean; icon: ReactNode; title: string; body: string; action: ReactNode }[] = [
    {
      done: connected,
      icon: <Laptop className="size-4" />,
      title: "Connect this machine",
      body: connected
        ? "Every Claude Code session here is captured, searchable, and can be handed on."
        : "One command. Your sessions start showing up here as you work — nothing else to change.",
      action: connected ? null : (
        <Link to="/connect">
          <Button size="sm" variant="primary">
            Get the command <ArrowRight className="size-3.5" />
          </Button>
        </Link>
      ),
    },
    {
      done: on,
      icon: <MoonStar className="size-4" />,
      title: "Never lose a session",
      body: on
        ? `Close your laptop mid-task and ${continuity.data?.agent?.name ?? "your AI developer"} carries the work on from where you stopped.`
        : "Turn on always-on sessions: if your machine goes offline mid-task, your own AI developer picks the work up.",
      action: on ? null : (
        <Button size="sm" variant="primary" loading={alwaysOn.isPending} onClick={() => alwaysOn.mutate()}>
          <MoonStar className="size-3.5" /> Turn it on
        </Button>
      ),
    },
    {
      done: hasRunner,
      icon: <Server className="size-4" />,
      title: "Give your agents somewhere to run",
      body: hasRunner
        ? "Your runner takes AI-developer work in sandboxes, with its own workbench and credentials."
        : "A runner is any machine with Docker. It is where AI developers work — and the only part that talks to the outside world.",
      action: hasRunner ? null : (
        <Link to="/ai">
          <Button size="sm" variant="primary">
            Add a runner <ArrowRight className="size-3.5" />
          </Button>
        </Link>
      ),
    },
    {
      done: otherAgents.length > 0,
      icon: <Cpu className="size-4" />,
      title: "Put an AI developer on a real ticket",
      body:
        otherAgents.length > 0
          ? "It works in a sandbox against its own database, runs your tests, and opens a pull request."
          : "Give it a workbench with your schema, and it can run what it writes before you read a line of it.",
      action:
        otherAgents.length > 0 ? null : me.user.role === "admin" ? (
          <Button size="sm" variant="primary" onClick={() => setHiring(true)}>
            <Sparkles className="size-3.5" /> Hire one
          </Button>
        ) : (
          <span className="text-xs text-muted">An admin creates these.</span>
        ),
    },
  ];
  const done = steps.filter((s) => s.done).length;

  return (
    <>
      <Card className="mb-6 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Set up your AI SDLC</h2>
            <p className="text-xs text-muted">
              {done === steps.length
                ? "All set. This panel is only here until you dismiss it."
                : `${done} of ${steps.length} done — about four minutes.`}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => dismiss.mutate()} loading={dismiss.isPending}>
            Dismiss
          </Button>
        </div>
        <ol className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-4">
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
        {me.user.role === "admin" && (
          <p className="border-t border-line px-4 py-2.5 text-xs text-muted">
            Working with a team?{" "}
            <Link to="/people" className="text-accent-ink hover:underline">
              Invite them
            </Link>{" "}
            — everyone connects their own machine, and each person sees their own work. Leads see their teams.
          </p>
        )}
      </Card>
      <NewAiDeveloper open={hiring} onClose={() => setHiring(false)} />
    </>
  );
}
