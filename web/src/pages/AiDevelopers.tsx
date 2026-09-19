import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Pencil, Plus, Server, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Dialog } from "../components/Dialog";
import { Badge, Button, Card, CopyButton, ErrorNote, Field, Input, PageHeader, Spinner } from "../components/ui";
import { BotAvatar, Segmented, Select, Textarea, TaskStatus, money, tokens } from "../components/work";
import { api } from "../lib/api";
import { prettyModel, relativeTime } from "../lib/format";
import type { AiDeveloper, ConnectInfo, Me, Runner, Team, User } from "../lib/types";

export function AiDevelopersPage({ me }: { me: Me }) {
  const isAdmin = me.user.role === "admin";
  const devs = useQuery({ queryKey: ["ai-developers"], queryFn: () => api<AiDeveloper[]>("/api/ai-developers"), refetchInterval: 5000 });
  const runners = useQuery({ queryKey: ["runners"], queryFn: () => api<Runner[]>("/api/runners"), refetchInterval: 5000 });
  const [editing, setEditing] = useState<AiDeveloper | "new" | null>(null);
  const [addingRunner, setAddingRunner] = useState(false);
  const onlineRunners = (runners.data ?? []).filter((r) => r.online);

  return (
    <div>
      <PageHeader
        title="AI developers"
        sub="Members of your organisation who are agents. Assign them tasks like anyone else; they work in sandboxes on your runners and open pull requests."
        actions={
          isAdmin && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus className="size-4" /> New AI developer
            </Button>
          )
        }
      />

      {devs.data && devs.data.length > 0 && onlineRunners.length === 0 && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-ink">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
          <div>
            <span className="font-medium">No runner is online.</span> Tasks for AI developers wait in the queue until one is.{" "}
            {isAdmin ? "Add a runner below and start it on any machine with Docker." : "Ask an admin to start a runner."}
          </div>
        </div>
      )}

      {devs.isLoading ? (
        <Spinner />
      ) : devs.data?.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {devs.data.map((d) => (
            <Card key={d.id} className={"p-5 " + (d.is_active ? "" : "opacity-60")}>
              <div className="flex items-start gap-3">
                <BotAvatar id={d.id} size={42} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-semibold">{d.name}</h3>
                    {!d.is_active && <Badge>Retired</Badge>}
                  </div>
                  <div className="text-sm text-muted">
                    {d.agent_vendor === "codex" ? "Codex" : "Claude Code"} · {d.agent_model ? prettyModel(d.agent_model) : "default model"}
                  </div>
                </div>
                {isAdmin && (
                  <Button size="sm" variant="ghost" onClick={() => setEditing(d)} aria-label={`Edit ${d.name}`}>
                    <Pencil className="size-3.5" />
                  </Button>
                )}
              </div>
              <div className="mt-4 rounded-lg bg-surface-2 px-3 py-2.5 text-sm">
                {d.current_task ? (
                  <Link to={`/tasks?view=all&task=${d.current_task.id}`} className="flex items-center gap-2 hover:underline">
                    <TaskStatus status={d.current_task.status} />
                    <span className="truncate">{d.current_task.title}</span>
                  </Link>
                ) : (
                  <span className="text-muted">Idle, ready for work</span>
                )}
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                <Stat label="Done" value={String(d.stats.tasks.succeeded ?? 0)} />
                <Stat label="Failed" value={String(d.stats.tasks.failed ?? 0)} />
                <Stat label="Cost" value={money(d.stats.cost_usd)} />
              </dl>
              <div className="mt-4 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                {d.sponsor && <span>Sponsored by {d.sponsor.name}</span>}
                {d.teams.map((t) => (
                  <Badge key={t.id}>{t.name}</Badge>
                ))}
                {d.runner_pool && <Badge>pool: {d.runner_pool}</Badge>}
                <span className="ml-auto">{tokens(d.stats.tokens)} tokens</span>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="px-6 py-12 text-center">
          <div className="mx-auto w-fit">
            <BotAvatar id="new" size={44} />
          </div>
          <p className="mt-3 font-medium">No AI developers yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            Give an agent a name, a model and a sponsor who answers for its work. Then assign it tasks, or make it the assignee of a
            workflow.
          </p>
          {isAdmin && (
            <Button size="sm" className="mt-4" onClick={() => setEditing("new")}>
              <Plus className="size-3.5" /> New AI developer
            </Button>
          )}
        </Card>
      )}

      <div className="mt-10 mb-3 flex items-end justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Runners</h2>
          <p className="text-sm text-muted">Machines in your network that run AI-developer sessions in Docker sandboxes. Model and git credentials stay on them.</p>
        </div>
        {isAdmin && (
          <Button onClick={() => setAddingRunner(true)}>
            <Server className="size-4" /> Add runner
          </Button>
        )}
      </div>
      <Card className="overflow-hidden">
        {runners.data?.length ? (
          <table className="w-full text-sm">
            <thead className="border-b border-line bg-surface-2/60 text-left text-[11.5px] tracking-wide text-muted uppercase">
              <tr>
                <th className="py-2.5 pr-3 pl-4 font-medium">Runner</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Can run</th>
                <th className="px-3 py-2.5 font-medium">Busy</th>
                {isAdmin && <th />}
              </tr>
            </thead>
            <tbody>
              {runners.data.map((r) => (
                <RunnerRow key={r.id} r={r} isAdmin={isAdmin} />
              ))}
            </tbody>
          </table>
        ) : (
          <p className="px-4 py-6 text-center text-sm text-muted">No runners yet.</p>
        )}
      </Card>

      {editing && <AiDevDialog me={me} dev={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {addingRunner && <AddRunnerDialog onClose={() => setAddingRunner(false)} />}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line py-2">
      <div className="tabular text-[15px] font-semibold">{value}</div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  );
}

function RunnerRow({ r, isAdmin }: { r: Runner; isAdmin: boolean }) {
  const qc = useQueryClient();
  const revoke = useMutation({
    mutationFn: () => api(`/api/runners/${r.id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runners"] }),
  });
  const caps = r.capabilities ?? {};
  const cap = (key: string, label: string) => (caps[key] ? <Badge key={key} tone="live">{label}</Badge> : <Badge key={key}>no {label.toLowerCase()}</Badge>);
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="py-3 pr-3 pl-4">
        <div className="font-medium">{r.name}</div>
        <div className="text-xs text-muted">
          <span className="font-mono">{r.token_prefix}…</span>
          {r.pool && ` · pool ${r.pool}`}
          {r.platform && ` · ${r.platform}`}
        </div>
      </td>
      <td className="px-3 py-3">
        {r.online ? (
          <Badge tone="live">
            <span className="live-dot !size-1.5" /> Online
          </Badge>
        ) : (
          <span className="text-muted">{r.last_seen_at ? `Last seen ${relativeTime(r.last_seen_at)}` : "Never connected"}</span>
        )}
      </td>
      <td className="px-3 py-3">
        {r.last_seen_at ? (
          <div className="flex flex-wrap gap-1">
            {cap("claude", "Claude Code")}
            {cap("codex", "Codex")}
            {cap("git_push", "Git push")}
            <Badge>{String(caps.backend ?? "docker")}</Badge>
          </div>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className="tabular px-3 py-3">
        {r.running} / {r.capacity}
      </td>
      {isAdmin && (
        <td className="py-3 pr-4 pl-3 text-right">
          <Button size="sm" variant="ghost" aria-label={`Remove ${r.name}`} onClick={() => confirm(`Remove runner ${r.name}? Its token stops working.`) && revoke.mutate()}>
            <Trash2 className="size-3.5" />
          </Button>
        </td>
      )}
    </tr>
  );
}

function AiDevDialog({ me, dev, onClose }: { me: Me; dev: AiDeveloper | null; onClose: () => void }) {
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/api/users") });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api<Team[]>("/api/teams") });
  const [name, setName] = useState(dev?.name ?? "");
  const [vendor, setVendor] = useState<"claude-code" | "codex">(dev?.agent_vendor ?? "claude-code");
  const [model, setModel] = useState(dev?.agent_model ?? "");
  const [sponsor, setSponsor] = useState(dev?.sponsor?.id ?? me.user.id);
  const [pool, setPool] = useState(dev?.runner_pool ?? "");
  const [instructions, setInstructions] = useState(dev?.instructions ?? "");
  const [teamIds, setTeamIds] = useState<string[]>(dev?.teams.map((t) => t.id) ?? []);
  const [active, setActive] = useState(dev?.is_active ?? true);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        agent_vendor: vendor,
        agent_model: model || null,
        sponsor_id: sponsor,
        runner_pool: pool || null,
        instructions: instructions || null,
        team_ids: teamIds,
        is_active: active,
      };
      return dev ? api(`/api/ai-developers/${dev.id}`, { method: "PUT", json: body }) : api("/api/ai-developers", { method: "POST", json: body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-developers"] });
      onClose();
    },
  });
  const models = vendor === "codex" ? ["gpt-5-codex", "gpt-5"] : ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"];

  return (
    <Dialog open onClose={onClose} title={dev ? `Edit ${dev.name}` : "New AI developer"} width={560}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Ada" />
          </Field>
          <Field label="Sponsor" hint="The person who answers for its work. Owns its sessions for audit.">
            <Select value={sponsor} onChange={(e) => setSponsor(e.target.value)}>
              {(people.data ?? [me.user]).filter((u) => u.is_active).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Agent">
          <Segmented value={vendor} onChange={setVendor} options={[{ value: "claude-code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Model" hint="Leave empty for the agent's default.">
            <Input value={model} onChange={(e) => setModel(e.target.value)} list="model-options" placeholder={models[0]} />
            <datalist id="model-options">
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </Field>
          <Field label="Runner pool" hint="Only runners in this pool take its tasks. Empty: runners with no pool.">
            <Input value={pool} onChange={(e) => setPool(e.target.value.toLowerCase())} placeholder="linux" pattern="[a-z0-9][a-z0-9_\-]*" />
          </Field>
        </div>
        <Field label="Standing instructions" hint="Prepended to every task: conventions, definition of done, what never to touch.">
          <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={4} placeholder="Write tests first. Keep PRs under 300 lines. Never change CI configuration." />
        </Field>
        {teams.data && teams.data.length > 0 && (
          <Field label="Teams" hint="Leads of these teams see its work.">
            <div className="flex flex-wrap gap-1.5">
              {teams.data.map((t) => {
                const on = teamIds.includes(t.id);
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setTeamIds(on ? teamIds.filter((x) => x !== t.id) : [...teamIds, t.id])}
                    className={"rounded-md border px-2 py-1 text-xs " + (on ? "border-accent bg-accent-soft text-accent-ink" : "border-line text-ink-2")}
                  >
                    {t.name}
                  </button>
                );
              })}
            </div>
          </Field>
        )}
        {dev && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-[var(--accent)]" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active (retired AI developers take no new tasks)
          </label>
        )}
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            {dev ? "Save" : "Create"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function AddRunnerDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["connect"], queryFn: () => api<ConnectInfo>("/api/connect") });
  const [name, setName] = useState("build-box");
  const [pool, setPool] = useState("");
  const [created, setCreated] = useState<Runner | null>(null);
  const create = useMutation({
    mutationFn: () => api<Runner>("/api/runners", { method: "POST", json: { name, pool: pool || null } }),
    onSuccess: (r) => {
      setCreated(r);
      qc.invalidateQueries({ queryKey: ["runners"] });
    },
  });
  const server = info.data?.server_url ?? window.location.origin;
  const steps = created
    ? [
        `curl -fsSL ${server}/install.sh | sh -s -- --runner-only`,
        `~/.flockit/venv/bin/flockit runner build-image`,
        `export ANTHROPIC_API_KEY=...   # or CLAUDE_CODE_OAUTH_TOKEN from \`claude setup-token\`\nexport GH_TOKEN=...            # to clone, push and open pull requests\n~/.flockit/venv/bin/flockit runner --server ${server} --token ${created.token}`,
      ]
    : [];
  return (
    <Dialog open onClose={onClose} title="Add a runner" width={640}>
      {!created ? (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <p className="text-sm text-muted">
            A runner is any machine in your network with Docker: a spare server, a VM, a CI host. Each task runs in a fresh container
            that is thrown away afterwards.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Pool (optional)">
              <Input value={pool} onChange={(e) => setPool(e.target.value.toLowerCase())} placeholder="linux" />
            </Field>
          </div>
          <ErrorNote error={create.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending}>
              Create runner token
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">Run these on the runner machine. The token is shown once.</p>
          {steps.map((s, i) => (
            <div key={i}>
              <div className="mb-1.5 text-xs font-medium text-muted">
                {i + 1}. {["Install the Flockit CLI", "Build the sandbox image (Claude Code and Codex inside)", "Start the runner"][i]}
              </div>
              <div className="relative rounded-lg bg-[#0d1729] text-[#e8ecf1]">
                <pre className="overflow-x-auto p-3 pr-24 font-mono text-[12px] leading-relaxed">{s}</pre>
                <div className="absolute top-2 right-2">
                  <CopyButton text={s} />
                </div>
              </div>
            </div>
          ))}
          <div className="flex justify-end">
            <Button variant="primary" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
