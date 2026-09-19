import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, Laptop, MessageSquare, ShieldCheck, Sparkles, Terminal, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Button, Card, CopyButton, ErrorNote, Input, PageHeader, Spinner } from "../components/ui";
import { api, qs } from "../lib/api";
import { prettyModel, relativeTime, shortRepo } from "../lib/format";
import type { ConnectInfo, Machine, Me, SessionPage, Token } from "../lib/types";

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="relative rounded-xl bg-[#0d1729] text-[#e8ecf1]">
      <pre className="overflow-x-auto px-4 py-3.5 pr-24 font-mono text-[13px] leading-relaxed">
        <code>{code}</code>
      </pre>
      <div className="absolute top-2.5 right-2.5">
        <CopyButton text={code} />
      </div>
    </div>
  );
}

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return (
    <li className="group relative flex gap-4 pb-8 last:pb-0">
      <span className="absolute top-8 bottom-0 left-[13px] w-px bg-line group-last:hidden" aria-hidden />
      <span
        className={
          "tabular relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold " +
          (done ? "bg-live text-white" : "bg-ink text-bg")
        }
      >
        {done ? <CheckCircle2 className="size-4" /> : n}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <h3 className="font-semibold">{title}</h3>
        <div className="mt-2 text-sm text-muted">{children}</div>
      </div>
    </li>
  );
}

export function ConnectPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [name, setName] = useState("My laptop");
  const [created, setCreated] = useState<{ token: string; at: string } | null>(null);

  const info = useQuery({ queryKey: ["connect"], queryFn: () => api<ConnectInfo>("/api/connect") });
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => api<Token[]>("/api/tokens") });

  const create = useMutation({
    mutationFn: () => api<Token & { token: string }>("/api/tokens", { method: "POST", json: { name } }),
    onSuccess: (t) => {
      setCreated({ token: t.token, at: t.created_at });
      qc.invalidateQueries({ queryKey: ["tokens"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api/tokens/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }),
  });

  // After a token is created, watch for this person's first session to arrive.
  const firstSession = useQuery({
    queryKey: ["first-session", created?.at],
    enabled: !!created,
    queryFn: () =>
      api<SessionPage>(`/api/sessions${qs({ owner: me.user.id, since: created!.at, limit: 1 })}`),
    refetchInterval: (q) => (q.state.data?.items.length ? false : 3000),
  });
  const arrived = firstSession.data?.items[0];

  const server = info.data?.server_url ?? window.location.origin;
  const command = `curl -fsSL ${server}/install.sh | sh -s -- ${created?.token ?? "<token>"}`;

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Connect Claude Code"
        sub="Install the collector once per machine. Every Claude Code session on it then shows up in Flockit, owned by you."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="p-6 sm:p-8">
          <ol>
            <Step n={1} title="Create your collector token" done={!!created}>
              <p>The token ties sessions on this machine to you. It is shown once and stored only as a hash.</p>
              {!created ? (
                <form
                  className="mt-3 flex max-w-md gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    create.mutate();
                  }}
                >
                  <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Token name" maxLength={120} />
                  <Button type="submit" variant="primary" loading={create.isPending}>
                    <KeyRound className="size-4" /> Create
                  </Button>
                </form>
              ) : (
                <p className="mt-2 text-ink">
                  Token <span className="font-mono">{created.token.slice(0, 10)}…</span> created. It is already in the
                  command below.
                </p>
              )}
              <ErrorNote error={create.error} />
            </Step>
            <Step n={2} title="Run this on the machine that runs Claude Code" done={!!arrived}>
              <p className="mb-3">
                It installs Flockit from this server into <span className="font-mono text-ink">~/.flockit</span>, registers it as a
                Claude Code hook, and starts a small background agent so tasks assigned to you can open here. Needs Python 3.9+.
                No internet access required.
              </p>
              {info.data && !info.data.collector_available ? (
                <ErrorNote error="This server build does not include the collector package. Use the Docker image, or run `make collector` before starting the server." />
              ) : (
                <CodeBlock code={command} />
              )}
              {me.user.role === "admin" && info.data && info.data.server_url_source !== "env" && (
                <ServerAddress current={server} fromRequest={info.data.server_url_source === "request"} />
              )}
            </Step>
            <Step n={3} title="Start a Claude Code session" done={!!arrived}>
              {!created ? (
                <p>Once the collector is installed, your next session appears here and on the Sessions page.</p>
              ) : arrived ? (
                <div className="mt-1 flex flex-wrap items-center gap-2 rounded-lg bg-live-soft px-3 py-2.5 text-live">
                  <CheckCircle2 className="size-4" />
                  <span className="font-medium">Connected.</span>
                  <span className="text-ink-2">
                    {prettyModel(arrived.agent_model)} in {shortRepo(arrived.repo) || "a folder with no repo"},{" "}
                    {relativeTime(arrived.started_at)}.
                  </span>
                  <Link to="/" className="ml-auto font-medium text-live hover:underline">
                    Open Sessions →
                  </Link>
                </div>
              ) : (
                <div className="mt-1 flex items-center gap-2 text-ink-2">
                  <Spinner className="size-3.5" /> Waiting for your first session. Open a terminal and run{" "}
                  <span className="font-mono text-ink">claude</span>.
                </div>
              )}
            </Step>
          </ol>
        </Card>

        <div className="space-y-6">
          <Card className="p-5">
            <div className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="size-4 text-live" /> What is captured
            </div>
            <ul className="mt-3 space-y-1.5 text-sm text-ink-2">
              {["Who, which agent and model, repo, branch, ticket", "The conversation: prompts, replies, tool calls", "Files edited, commands run, token usage"].map(
                (t) => (
                  <li key={t} className="flex gap-2">
                    <span className="mt-2 size-1 shrink-0 rounded-full bg-live" />
                    {t}
                  </li>
                ),
              )}
            </ul>
            <p className="mt-3 text-xs leading-relaxed text-muted">
              Everything is redacted on your laptop before it is sent: API keys, tokens, passwords and connection strings are
              stripped, and paths are made relative so your username never leaves. It goes only to this server.
            </p>
          </Card>

          <MyMachines />

          <EditorAccess server={info.data?.server_url ?? ""} />

          <SlackLink me={me} />

          <Card className="p-5">
            <div className="flex items-center gap-2 font-semibold">
              <Terminal className="size-4 text-muted" /> Your tokens
            </div>
            {tokens.data && tokens.data.length === 0 && <p className="mt-2 text-sm text-muted">No tokens yet.</p>}
            <ul className="mt-2 divide-y divide-line">
              {tokens.data?.map((t) => (
                <li key={t.id} className="flex items-center gap-2 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{t.name}</div>
                    <div className="truncate text-xs text-muted">
                      <span className="font-mono">{t.prefix}…</span> ·{" "}
                      {t.last_used_at ? `used ${relativeTime(t.last_used_at)}` : "never used"}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Revoke ${t.name}`}
                    title="Revoke"
                    onClick={() => confirm(`Revoke "${t.name}"? Its collector stops reporting immediately.`) && revoke.mutate(t.id)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted">
              To remove the collector from a machine, run <span className="font-mono">flockit uninstall</span>.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** Admins can correct the address developers' machines use. Set once; pinned against Host headers. */
function ServerAddress({ current, fromRequest }: { current: string; fromRequest: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(current);
  const save = useMutation({
    mutationFn: () => api("/api/connect/public-url", { method: "PUT", json: { public_url: value } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connect"] });
      setEditing(false);
    },
  });
  return (
    <div className={"mt-3 rounded-lg px-3 py-2.5 text-xs leading-relaxed " + (fromRequest ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted")}>
      {!editing ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>
            Developers' machines will contact <span className="font-mono text-ink">{current}</span>.
            {fromRequest && " Confirm it is reachable from their network."}
          </span>
          <button onClick={() => setEditing(true)} className="font-medium text-accent-ink hover:underline">
            Change
          </button>
        </div>
      ) : (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Input value={value} onChange={(e) => setValue(e.target.value)} className="h-8 max-w-sm font-mono text-xs" aria-label="Server address" />
          <Button size="sm" variant="primary" type="submit" loading={save.isPending}>
            Save
          </Button>
          <Button size="sm" variant="ghost" type="button" onClick={() => setEditing(false)}>
            Cancel
          </Button>
          {save.error && <span className="w-full text-bad">{(save.error as Error).message}</span>}
        </form>
      )}
    </div>
  );
}

function MyMachines() {
  const qc = useQueryClient();
  const machines = useQuery({ queryKey: ["my-machines"], queryFn: () => api<Machine[]>("/api/machines/me"), refetchInterval: 10000 });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/machines/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-machines"] }),
  });
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 font-semibold">
        <Laptop className="size-4 text-muted" /> Your machines
      </div>
      {machines.data?.length ? (
        <ul className="mt-2 divide-y divide-line">
          {machines.data.map((m) => (
            <li key={m.id} className="flex items-center gap-2 py-2.5">
              <span className={"size-2 shrink-0 rounded-full " + (m.online ? "bg-live" : "bg-line-strong")} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{m.name}</div>
                <div className="truncate text-xs text-muted">
                  {m.online ? "Agent running, ready for tasks" : m.last_seen_at ? `Offline · seen ${relativeTime(m.last_seen_at)}` : "Never connected"}
                </div>
              </div>
              <Button size="sm" variant="ghost" aria-label={`Remove ${m.name}`} onClick={() => confirm(`Stop sending tasks to ${m.name}?`) && remove.mutate(m.id)}>
                <Trash2 className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">No machine has connected its agent yet.</p>
      )}
    </Card>
  );
}


/**
 * The org's memory, inside the editor. One token, one command, and a Claude Code session
 * can search every session the person is allowed to see — and hand work to an AI developer
 * without leaving the terminal.
 */
function EditorAccess({ server }: { server: string }) {
  const qc = useQueryClient();
  const [token, setToken] = useState<string | null>(null);
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => api<Token[]>("/api/tokens") });
  const existing = (tokens.data ?? []).filter((t) => t.kind === "mcp");
  const create = useMutation({
    mutationFn: () => api<{ token: string }>("/api/tokens", { method: "POST", json: { kind: "mcp", name: "Editor (MCP)" } }),
    onSuccess: (created) => {
      setToken(created.token);
      qc.invalidateQueries({ queryKey: ["tokens"] });
    },
  });

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 font-semibold">
        <Sparkles className="size-4 text-accent" /> Your editor
      </div>
      <p className="mt-2 text-sm leading-relaxed text-ink-2">
        Let Claude Code ask Flockit what the team already knows: <span className="italic">"has anyone hit this error
        before?"</span>, <span className="italic">"what did Ada change last night?"</span> — and hand work over without
        leaving the session.
      </p>
      {token ? (
        <div className="mt-3 space-y-2">
          <CodeBlock code={`flockit mcp install --token ${token}`} />
          <p className="text-xs text-muted">
            Copy it now — it is shown once. It can read what you can read, and cannot send sessions.
          </p>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" loading={create.isPending} onClick={() => create.mutate()}>
            <KeyRound className="size-3.5" /> Create an editor token
          </Button>
          {existing.length > 0 && <span className="text-xs text-muted">{existing.length} active</span>}
        </div>
      )}
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Works with anything that speaks MCP. {server ? `Points at ${server}.` : ""}
      </p>
    </Card>
  );
}

/**
 * Slack is linked from the side that already knows who you are: Flockit shows a code, you
 * type it into Slack. No directory sync, and Flockit never calls Slack to look anyone up.
 */
function SlackLink({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [code, setCode] = useState<string | null>(null);
  const status = useQuery({ queryKey: ["slack-status"], queryFn: () => api<{ configured: boolean }>("/api/slack/status") });
  const make = useMutation({
    mutationFn: () => api<{ command: string; expires_in_minutes: number }>("/api/connect/slack-code", { method: "POST" }),
    onSuccess: (r) => setCode(r.command),
  });
  const unlink = useMutation({
    mutationFn: () => api("/api/connect/slack-code", { method: "DELETE" }),
    onSuccess: () => {
      setCode(null);
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  if (!status.data?.configured) {
    return (
      <Card className="p-5">
        <div className="flex items-center gap-2 font-semibold">
          <MessageSquare className="size-4 text-muted" /> Slack
        </div>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Not connected on this Flockit. An admin can set it up in about five minutes —{" "}
          <span className="font-mono text-xs">docs/slack.md</span> — and then{" "}
          <span className="font-mono text-xs">/flockit ada fix the flaky test</span> works from any channel.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 font-semibold">
        <MessageSquare className="size-4 text-accent" /> Slack
      </div>
      {me.slack_linked ? (
        <>
          <p className="mt-2 flex items-center gap-2 text-sm text-ink-2">
            <CheckCircle2 className="size-4 text-live" /> Linked. Try{" "}
            <span className="font-mono text-xs">/flockit ada …</span>
          </p>
          <Button size="sm" variant="ghost" className="mt-2" loading={unlink.isPending} onClick={() => unlink.mutate()}>
            Unlink
          </Button>
        </>
      ) : code ? (
        <div className="mt-3 space-y-2">
          <CodeBlock code={code} />
          <p className="text-xs text-muted">Paste that into any Slack channel. It expires in 15 minutes.</p>
        </div>
      ) : (
        <>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">
            Start work from where the conversation happens, and get the result back in the same thread.
          </p>
          <Button size="sm" variant="primary" className="mt-3" loading={make.isPending} onClick={() => make.mutate()}>
            Link my Slack account
          </Button>
        </>
      )}
    </Card>
  );
}
