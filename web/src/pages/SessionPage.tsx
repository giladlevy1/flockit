import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, ArrowRight, ChevronRight, FileCode2, Forward, GitBranch, ListTodo, MoonStar, Play, Terminal, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router";

import { Markdown } from "../components/Markdown";
import { StatusBadge } from "../components/sessions/StatusBadge";
import { NewTaskDialog } from "../components/tasks/NewTaskDialog";
import { Avatar, Badge, Button, Card, Spinner } from "../components/ui";
import { BotAvatar, Segmented, TaskStatus, tokens } from "../components/work";
import { api } from "../lib/api";
import { dateTime, duration, prettyModel, shortRepo, taskHref, taskLabel, vendorLabel } from "../lib/format";
import type { Me, Session, TranscriptMessage } from "../lib/types";

export function SessionPage({ me }: { me: Me }) {
  const { id } = useParams();
  const location = useLocation();
  const session = useQuery({
    queryKey: ["session", id],
    queryFn: () => api<Session>(`/api/sessions/${id}`),
    refetchInterval: (q) => (q.state.data?.status === "live" ? 4000 : false),
  });
  const files = useQuery({ queryKey: ["session-files", id], queryFn: () => api<{ path: string; edits: number }[]>(`/api/sessions/${id}/files`) });
  const transcript = useInfiniteQuery({
    queryKey: ["transcript", id],
    queryFn: ({ pageParam }) =>
      api<{ items: TranscriptMessage[]; has_more: boolean }>(`/api/sessions/${id}/transcript?after=${pageParam}&limit=500`),
    initialPageParam: -1,
    getNextPageParam: (last) => (last.has_more ? last.items[last.items.length - 1].seq : undefined),
    refetchInterval: session.data?.status === "live" ? 4000 : false,
  });
  const [showTools, setShowTools] = useState(true);
  const [view, setView] = useState<"chat" | "terminal">("chat");
  const [handoff, setHandoff] = useState(false);
  const messages = useMemo(() => transcript.data?.pages.flatMap((p) => p.items) ?? [], [transcript.data]);
  const target = location.hash.startsWith("#m-") ? Number(location.hash.slice(3)) : null;

  useEffect(() => {
    if (target == null || !messages.length) return;
    document.getElementById(`m-${target}`)?.scrollIntoView({ block: "center" });
  }, [target, messages.length]);

  if (session.isLoading) return <Spinner />;
  if (!session.data) return <p className="text-sm text-bad">This session is not visible to you.</p>;
  const s = session.data;
  const visible = showTools ? messages : messages.filter((m) => m.kind === "text");

  return (
    <div>
      <Link to="/" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Sessions
      </Link>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-start gap-3">
            {s.actor?.kind === "ai" ? <BotAvatar id={s.actor.id} size={40} /> : <Avatar name={s.owner.name} id={s.owner.id} size={40} />}
            <div className="min-w-0 flex-1 basis-60">
              <h1 className="text-xl leading-snug font-semibold tracking-tight">{s.title ?? "Untitled session"}</h1>
              <div className="mt-1 text-sm text-muted">
                {s.actor ? (
                  <>
                    <span className="font-medium text-ink">{s.actor.name}</span> for {s.owner.name}
                  </>
                ) : (
                  <span className="font-medium text-ink">{s.owner.name}</span>
                )}{" "}
                · {vendorLabel(s.agent_vendor)} · {prettyModel(s.agent_model)} · {dateTime(s.started_at)}
              </div>
            </div>
            <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">
              <StatusBadge s={s} />
              {s.owner.id === me.user.id && s.agent_vendor === "claude-code" && s.origin !== "workflow" && (
                <Continue id={s.id} />
              )}
              <Button size="sm" onClick={() => setHandoff(true)} title="Turn this session into a task for someone else, or for an AI developer">
                <Forward className="size-3.5" /> Hand off
              </Button>
            </div>
          </div>

          <Handoff s={s} />

          <Card className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
              <Segmented
                value={view}
                onChange={setView}
                options={[
                  { value: "chat", label: "Conversation" },
                  { value: "terminal", label: "Terminal" },
                ]}
              />
              {view === "chat" && (
                <label className="flex items-center gap-2 text-[13px] text-muted">
                  <input type="checkbox" className="accent-[var(--accent)]" checked={showTools} onChange={(e) => setShowTools(e.target.checked)} />
                  Show tool calls
                </label>
              )}
            </div>
            {transcript.isLoading ? (
              <div className="p-6">
                <Spinner />
              </div>
            ) : visible.length === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-muted">
                No conversation captured for this session. It may predate transcript capture, or the collector is older than 0.2.
              </p>
            ) : view === "terminal" ? (
              <TerminalView messages={messages} />
            ) : (
              <ol className="divide-y divide-line">
                {visible.map((m) => (
                  <Message key={`${m.seq}-${m.kind}`} m={m} highlighted={m.seq === target} actor={s.actor} owner={s.owner} />
                ))}
              </ol>
            )}
            {transcript.hasNextPage && (
              <button onClick={() => transcript.fetchNextPage()} className="w-full border-t border-line py-2.5 text-sm text-accent-ink hover:bg-surface-2">
                Load more
              </button>
            )}
          </Card>
        </div>

        <aside className="space-y-4">
          <Card className="grid grid-cols-2 gap-px overflow-hidden bg-line p-0">
            {[
              ["Duration", duration(s.duration_seconds)],
              ["Turns", String(s.turn_count)],
              ["Tool calls", String(s.tool_calls)],
              ["Files", String(s.files_touched)],
              ["Tokens in", tokens(s.tokens_input + s.tokens_cache_read + s.tokens_cache_write)],
              ["Tokens out", tokens(s.tokens_output)],
            ].map(([label, value]) => (
              <div key={label} className="bg-surface px-4 py-3">
                <div className="text-[11px] text-muted">{label}</div>
                <div className="tabular text-[17px] font-semibold">{value}</div>
              </div>
            ))}
          </Card>

          {s.task && (
            <Link to={`/tasks?view=all&task=${s.task.id}`} className="block">
              <Card className="p-4 hover:border-line-strong">
                <div className="flex items-center gap-2 text-xs font-medium tracking-wide text-muted uppercase">
                  <ListTodo className="size-3.5" /> Task
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{s.task.title}</span>
                  <TaskStatus status={s.task.status} />
                </div>
              </Card>
            </Link>
          )}

          <Card className="p-4 text-sm">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <GitBranch className="size-4 text-muted" />
                <span className="truncate font-mono text-[13px]">{shortRepo(s.repo) || "no repo"}</span>
              </div>
              {s.branch && <div className="pl-6 font-mono text-[12.5px] break-all text-muted">{s.branch}</div>}
              {s.task_ref && (
                <div className="pl-6">
                  {taskHref(s.task_ref) ? (
                    <a href={s.task_ref} target="_blank" rel="noreferrer noopener" className="text-accent-ink hover:underline">
                      {taskLabel(s.task_ref)}
                    </a>
                  ) : (
                    <span className="font-mono">{s.task_ref}</span>
                  )}
                </div>
              )}
            </div>
          </Card>

          <Card className="p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium tracking-wide text-muted uppercase">
              <FileCode2 className="size-3.5" /> Files changed
            </div>
            {files.data?.length ? (
              <ul className="space-y-1">
                {files.data.map((f) => (
                  <li key={f.path} className="flex items-center justify-between gap-2 font-mono text-[12.5px]">
                    <span className="truncate" title={f.path}>
                      {f.path}
                    </span>
                    <span className="tabular shrink-0 text-muted">×{f.edits}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No file edits recorded.</p>
            )}
          </Card>
          <p className="px-1 text-xs leading-relaxed text-muted">
            Captured on the developer's machine and redacted there: credentials are stripped and paths are made relative before
            anything is sent.
          </p>
        </aside>
      </div>
      {handoff && (
        <NewTaskDialog
          me={me}
          open
          onClose={() => setHandoff(false)}
          initial={{
            title: s.title ? `Continue: ${s.title}`.slice(0, 280) : "Continue this work",
            prompt: handoffPrompt(s, messages),
            repo: s.repo ?? "",
            base_branch: s.branch && !["main", "master"].includes(s.branch) ? s.branch : "",
            task_ref: s.task_ref ?? "",
          }}
        />
      )}
    </div>
  );
}

/** A starting prompt that carries the useful context of a session to whoever continues it. */
function handoffPrompt(s: Session, messages: TranscriptMessage[]): string {
  const asks = messages.filter((m) => m.kind === "text" && m.role === "user").slice(0, 3).map((m) => m.content.slice(0, 600));
  const lastReply = [...messages].reverse().find((m) => m.kind === "text" && m.role === "assistant");
  const files = [...new Set(messages.filter((m) => m.kind === "tool_use" && m.tool_name && ["Edit", "Write", "MultiEdit"].includes(m.tool_name)).map((m) => m.content.split("\n")[0]))].slice(0, 12);
  return [
    `Continue the work from an earlier session${s.branch ? ` on branch \`${s.branch}\`` : ""}.`,
    "",
    "What was asked:",
    ...asks.map((a) => `- ${a.replace(/\s+/g, " ")}`),
    ...(lastReply ? ["", "Where it ended:", lastReply.content.slice(0, 1500)] : []),
    ...(files.length ? ["", "Files it touched:", ...files.map((f) => `- ${f}`)] : []),
    "",
    "Pick up from there: check what is already done, finish what is left, and verify it.",
  ].join("\n");
}

function Message({
  m,
  highlighted,
  actor,
  owner,
}: {
  m: TranscriptMessage;
  highlighted: boolean;
  actor: Session["actor"];
  owner: Session["owner"];
}) {
  const [open, setOpen] = useState(highlighted);
  const time = new Date(m.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (m.kind === "text") {
    const fromPerson = m.role === "user";
    return (
      <li id={`m-${m.seq}`} className={clsx("flex gap-3 px-4 py-4", highlighted && "bg-accent-soft/50")}>
        <div className="pt-0.5">
          {fromPerson ? (
            actor?.kind === "ai" ? (
              <span className="flex size-7 items-center justify-center rounded-lg bg-surface-2 text-muted">
                <ListTodo className="size-3.5" />
              </span>
            ) : (
              <Avatar name={owner.name} id={owner.id} size={28} />
            )
          ) : (
            <span className="flex size-7 items-center justify-center rounded-lg bg-ink text-bg">
              <Terminal className="size-3.5" />
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-baseline gap-2 text-xs">
            <span className="font-semibold text-ink">{fromPerson ? (actor?.kind === "ai" ? "Task prompt" : owner.name) : "Agent"}</span>
            <span className="text-muted">{time}</span>
          </div>
          <Markdown text={m.content} className="text-ink-2" />
        </div>
      </li>
    );
  }
  const isResult = m.kind === "tool_result";
  const firstLine = m.content.split("\n")[0].slice(0, 140);
  const error = isResult && m.content.startsWith("[error]");
  return (
    <li id={`m-${m.seq}`} className={clsx("px-4 py-1.5", highlighted && "bg-accent-soft/50")}>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 rounded-md py-1 text-left text-[12.5px] text-muted hover:text-ink">
        <ChevronRight className={clsx("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        {isResult ? <span className={clsx("shrink-0", error && "text-bad")}>{error ? "Error" : "Result"}</span> : <Wrench className="size-3.5 shrink-0" />}
        {!isResult && <span className="shrink-0 font-medium text-ink-2">{m.tool_name}</span>}
        <span className="truncate font-mono">{firstLine}</span>
      </button>
      {open && <pre className="mt-1 mb-2 ml-5 max-h-96 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">{m.content}</pre>}
    </li>
  );
}

/**
 * Pick this conversation back up on your own machine: the agent reopens the original
 * Claude Code session with `--resume`, in the checkout it belongs to, so the context is
 * the one it had when you stopped.
 */
function Continue({ id }: { id: string }) {
  const qc = useQueryClient();
  const [note, setNote] = useState<string | null>(null);
  const go = useMutation({
    mutationFn: () => api<{ task_id: string; status: string; machine: string | null }>(`/api/sessions/${id}/continue`, { method: "POST" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      setNote(
        r.machine
          ? `Sent to ${r.machine}. Accept it there and Claude Code reopens this session.`
          : "Waiting for one of your machines to come online.",
      );
    },
  });
  if (note) return <span className="text-[13px] text-muted">{note}</span>;
  return (
    <Button size="sm" variant="primary" loading={go.isPending} onClick={() => go.mutate()} title="Reopen this session on your machine">
      <Play className="size-3.5" /> Continue
    </Button>
  );
}

/**
 * The same session read as what it was on the machine: what the agent ran, and what came
 * back. Commands first, prose reduced to comments — how you would read it if you had been
 * looking over their shoulder.
 */
function TerminalView({ messages }: { messages: TranscriptMessage[] }) {
  const lines = messages.filter((m) => m.kind !== "text" || m.role === "user");
  if (lines.length === 0) {
    return <p className="px-4 py-10 text-center text-sm text-muted">Nothing was run in this session.</p>;
  }
  return (
    <div className="max-h-[70vh] overflow-auto bg-[#0d1729] px-4 py-3 font-mono text-[12.5px] leading-relaxed text-[#e8ecf1]">
      {lines.map((m) => {
        if (m.kind === "text") {
          return (
            <p key={m.seq} className="mt-3 whitespace-pre-wrap text-[#7d8aa0] first:mt-0">
              {m.content
                .split("\n")
                .map((line) => `# ${line}`)
                .join("\n")}
            </p>
          );
        }
        if (m.kind === "tool_use") {
          const shell = m.tool_name === "Bash";
          return (
            <p key={`${m.seq}-u`} className="mt-2 whitespace-pre-wrap">
              <span className="text-[#e8622c]">{shell ? "$ " : `${m.tool_name ?? "tool"} `}</span>
              <span className="text-[#e8ecf1]">{m.content}</span>
            </p>
          );
        }
        return (
          <p key={`${m.seq}-r`} className="whitespace-pre-wrap text-[#9fb3c8]">
            {m.content}
          </p>
        );
      })}
    </div>
  );
}

/**
 * A session that was interrupted, and the one that carried on from it. Shown on both
 * ends so the work reads as one thread rather than two unrelated sessions.
 */
function Handoff({ s }: { s: Session }) {
  if (s.continued_by) {
    const live = s.continued_by.status === "running" || s.continued_by.status === "starting";
    return (
      <Card className="mt-4 flex flex-wrap items-center gap-3 border-accent/40 px-4 py-3">
        <MoonStar className="size-4 shrink-0 text-accent" />
        <span className="min-w-0 flex-1 text-sm">
          Your machine went offline mid-session, so this work {live ? "is being continued" : "was continued"} by your AI
          developer.
        </span>
        {s.continued_by.session_id ? (
          <Link to={`/sessions/${s.continued_by.session_id}`}>
            <Button size="sm" variant="secondary">
              Watch it <ArrowRight className="size-3.5" />
            </Button>
          </Link>
        ) : (
          <Badge tone="accent">{s.continued_by.status}</Badge>
        )}
      </Card>
    );
  }
  if (s.continues) {
    return (
      <Card className="mt-4 flex flex-wrap items-center gap-3 px-4 py-3">
        <MoonStar className="size-4 shrink-0 text-muted" />
        <span className="min-w-0 flex-1 text-sm text-ink-2">
          Continuing a session that stopped when its machine went offline.
        </span>
        <Link to={`/sessions/${s.continues.session_id}`} className="text-[13px] text-accent-ink hover:underline">
          See where it started
        </Link>
      </Card>
    );
  }
  return null;
}
