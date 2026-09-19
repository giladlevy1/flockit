import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, ShieldCheck, Terminal, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Button, Card, CopyButton, ErrorNote, Input, PageHeader, Spinner } from "../components/ui";
import { api, qs } from "../lib/api";
import { prettyModel, relativeTime, shortRepo } from "../lib/format";
import type { ConnectInfo, Me, SessionPage, Token } from "../lib/types";

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
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
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
                It installs the collector from this server into <span className="font-mono text-ink">~/.flockit</span> and
                registers it as a Claude Code hook. Needs Python 3.9+. No internet access required.
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
              <ShieldCheck className="size-4 text-live" /> What leaves the machine
            </div>
            <ul className="mt-3 space-y-1.5 text-sm text-ink-2">
              {["Session id, start and end time", "Agent, version and model", "Repo (no credentials, no local path)", "Branch and ticket reference"].map(
                (t) => (
                  <li key={t} className="flex gap-2">
                    <span className="mt-2 size-1 shrink-0 rounded-full bg-live" />
                    {t}
                  </li>
                ),
              )}
            </ul>
            <p className="mt-3 text-xs leading-relaxed text-muted">
              Never sent: prompts, responses, code, command output, file paths, environment variables. Secrets are
              redacted on the laptop before anything is transmitted.
            </p>
          </Card>

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
