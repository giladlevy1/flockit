import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Hand, Pencil, Play, Plus, Trash2, Webhook, Workflow as WorkflowIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Dialog } from "../components/Dialog";
import { useAssignees } from "../components/tasks/NewTaskDialog";
import { Badge, Button, Card, CopyButton, ErrorNote, Field, Input, PageHeader, Spinner } from "../components/ui";
import { PROFILE_TEXT, PersonChip, Segmented, Select, Textarea } from "../components/work";
import { api } from "../lib/api";
import { dateTime, relativeTime } from "../lib/format";
import type { Me, PermissionProfile, RunMode, Task, Workflow } from "../lib/types";

const PRESETS = [
  { label: "Every hour", cron: "0 * * * *" },
  { label: "Weekdays 09:00", cron: "0 9 * * 1-5" },
  { label: "Every day 02:00", cron: "0 2 * * *" },
  { label: "Mondays 08:00", cron: "0 8 * * 1" },
];

export function describeCron(cron: string): string {
  return PRESETS.find((p) => p.cron === cron)?.label ?? cron;
}

export function WorkflowsPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const canManage = me.user.role !== "developer";
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: () => api<Workflow[]>("/api/workflows"), refetchInterval: 15000 });
  const [editing, setEditing] = useState<Workflow | "new" | null>(null);
  const [created, setCreated] = useState<Workflow | null>(null);

  useEffect(() => {
    const open = params.get("open");
    if (open && workflows.data) {
      const wf = workflows.data.find((w) => w.id === open);
      if (wf && canManage) setEditing(wf);
      setParams({}, { replace: true });
    }
  }, [params, workflows.data, canManage, setParams]);

  const run = useMutation({
    mutationFn: (id: string) => api<Task>(`/api/workflows/${id}/run`, { method: "POST", json: {} }),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
      navigate(`/tasks?view=all&task=${t.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/workflows/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });

  return (
    <div>
      <PageHeader
        title="Workflows"
        sub="Repeatable work for people and AI developers. Run by hand, on a schedule, or when another system calls a webhook."
        actions={
          canManage && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus className="size-4" /> New workflow
            </Button>
          )
        }
      />
      <ErrorNote error={run.error ?? remove.error} />
      {workflows.isLoading ? (
        <Spinner />
      ) : workflows.data?.length ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {workflows.data.map((wf) => (
            <Card key={wf.id} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-semibold">{wf.name}</h3>
                    {!wf.enabled && <Badge>Paused</Badge>}
                  </div>
                  {wf.description && <p className="mt-0.5 line-clamp-2 text-sm text-muted">{wf.description}</p>}
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" onClick={() => run.mutate(wf.id)} loading={run.isPending && run.variables === wf.id} title="Run now">
                    <Play className="size-3.5" /> Run
                  </Button>
                  {canManage && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(wf)} aria-label={`Edit ${wf.name}`}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Delete ${wf.name}`}
                        onClick={() => confirm(`Delete "${wf.name}"? Its past tasks stay.`) && remove.mutate(wf.id)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </>
                  )}
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Badge>
                  <Hand className="size-3" /> Manual
                </Badge>
                {wf.schedule_cron && (
                  <Badge tone="accent">
                    <CalendarClock className="size-3" /> {describeCron(wf.schedule_cron)}
                    {wf.schedule_timezone !== "UTC" && ` (${wf.schedule_timezone})`}
                  </Badge>
                )}
                {wf.webhook_enabled && (
                  <Badge tone="accent">
                    <Webhook className="size-3" /> Webhook
                  </Badge>
                )}
                <Badge>{wf.mode === "auto" ? "Auto-start" : "Asks the assignee"}</Badge>
                <Badge>{PROFILE_TEXT[wf.permission_profile].label}</Badge>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3 text-sm">
                <PersonChip person={wf.assignee} size={22} sub={<span className="font-mono">{wf.repo}</span>} />
                <div className="text-right text-xs text-muted">
                  <Link to={`/tasks?view=all&status=all&workflow=${wf.id}`} className="hover:text-ink">
                    {(wf.runs.succeeded ?? 0) + (wf.runs.failed ?? 0)} finished · {wf.runs.failed ?? 0} failed
                  </Link>
                  <div>
                    {wf.last_run_at ? `last ${relativeTime(wf.last_run_at)}` : "never run"}
                    {wf.next_run_at && ` · next ${dateTime(wf.next_run_at)}`}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="flex flex-col items-center gap-2 px-6 py-14 text-center">
          <span className="flex size-10 items-center justify-center rounded-xl bg-accent-soft text-accent">
            <WorkflowIcon className="size-5" />
          </span>
          <p className="mt-2 font-medium">No workflows yet</p>
          <p className="max-w-md text-sm text-muted">
            For example: every new bug with the label <span className="font-mono">triage</span> goes to an AI developer, who
            reproduces it and opens a PR. Or every Monday, a dependency upgrade lands on someone's machine.
          </p>
          {canManage && (
            <Button size="sm" className="mt-2" onClick={() => setEditing("new")}>
              <Plus className="size-3.5" /> New workflow
            </Button>
          )}
        </Card>
      )}

      {editing && (
        <WorkflowEditor
          me={me}
          workflow={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(wf) => {
            setEditing(null);
            if (wf.webhook_url) setCreated(wf);
          }}
        />
      )}
      {created && <WebhookReady wf={created} onClose={() => setCreated(null)} />}
    </div>
  );
}

function WorkflowEditor({
  me,
  workflow,
  onClose,
  onSaved,
}: {
  me: Me;
  workflow: Workflow | null;
  onClose: () => void;
  onSaved: (wf: Workflow) => void;
}) {
  const qc = useQueryClient();
  const { humans, bots } = useAssignees(me);
  const [name, setName] = useState(workflow?.name ?? "");
  const [description, setDescription] = useState(workflow?.description ?? "");
  const [prompt, setPrompt] = useState(workflow?.prompt_template ?? "");
  const [repo, setRepo] = useState(workflow?.repo ?? "");
  const [baseBranch, setBaseBranch] = useState(workflow?.base_branch ?? "");
  const [assignee, setAssignee] = useState(workflow?.assignee.id ?? bots[0]?.id ?? me.user.id);
  const [mode, setMode] = useState<RunMode>(workflow?.mode ?? "auto");
  const [profile, setProfile] = useState<PermissionProfile>(workflow?.permission_profile ?? "edit");
  const [scheduled, setScheduled] = useState(!!workflow?.schedule_cron);
  const [cron, setCron] = useState(workflow?.schedule_cron ?? "0 9 * * 1-5");
  const [tz, setTz] = useState(workflow?.schedule_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
  const [webhook, setWebhook] = useState(workflow?.webhook_enabled ?? false);
  const [filter, setFilter] = useState(workflow?.webhook_filter ? JSON.stringify(workflow.webhook_filter) : "");
  const [enabled, setEnabled] = useState(workflow?.enabled ?? true);
  const [filterError, setFilterError] = useState<string | null>(null);
  const isBot = bots.some((b) => b.id === assignee);

  const save = useMutation({
    mutationFn: () => {
      let parsed: unknown = null;
      if (webhook && filter.trim()) {
        try {
          parsed = JSON.parse(filter);
        } catch {
          setFilterError('Not valid JSON. Example: {"path": "action", "equals": "opened"}');
          throw new Error("Fix the webhook filter");
        }
      }
      const body = {
        name,
        description: description || null,
        prompt_template: prompt,
        repo,
        base_branch: baseBranch || null,
        assignee_id: assignee,
        mode,
        permission_profile: profile,
        schedule_cron: scheduled ? cron : null,
        schedule_timezone: tz,
        webhook_enabled: webhook,
        webhook_filter: parsed,
        enabled,
      };
      return workflow
        ? api<Workflow>(`/api/workflows/${workflow.id}`, { method: "PUT", json: body })
        : api<Workflow>("/api/workflows", { method: "POST", json: body });
    },
    onSuccess: (wf) => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      onSaved(wf);
    },
  });
  const rotate = useMutation({
    mutationFn: () => api<Workflow>(`/api/workflows/${workflow!.id}/webhook-secret`, { method: "POST" }),
    onSuccess: (wf) => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      onSaved(wf);
    },
  });

  return (
    <Dialog open onClose={onClose} title={workflow ? `Edit ${workflow.name}` : "New workflow"} width={680}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setFilterError(null);
          save.mutate();
        }}
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Triage new bugs" />
          </Field>
          <Field label="Assign to">
            <Select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              {bots.length > 0 && (
                <optgroup label="AI developers">
                  {bots.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label="People">
                {humans.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </optgroup>
            </Select>
          </Field>
        </div>
        <Field label="Description (optional)">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this workflow is for" />
        </Field>
        <Field
          label="Prompt"
          hint={
            <>
              Use <span className="font-mono">{"{{payload.issue.title}}"}</span>-style placeholders to pull values from the webhook
              body. Missing values render empty.
            </>
          }
        >
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={6}
            required
            className="font-mono text-[13px]"
            placeholder={"A new bug was reported: {{payload.issue.title}}\n\n{{payload.issue.body}}\n\nReproduce it with a failing test, fix it, and open a PR."}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Repository">
            <Input value={repo} onChange={(e) => setRepo(e.target.value)} required placeholder="github.com/acme/api" />
          </Field>
          <Field label="Base branch">
            <Input value={baseBranch} onChange={(e) => setBaseBranch(e.target.value)} placeholder="main" />
          </Field>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {!isBot ? (
            <Field label="How it starts" hint={mode === "ask" ? "The assignee accepts each task." : "Starts headless if the assignee allows auto-start."} group>
              <Segmented value={mode} onChange={setMode} options={[{ value: "ask", label: "Ask" }, { value: "auto", label: "Auto-start" }]} />
            </Field>
          ) : (
            <Field label="How it starts" hint="AI developers start as soon as a runner is free." group>
              <div className="flex h-[38px] items-center text-sm text-ink-2">Automatically, in a sandbox</div>
            </Field>
          )}
          <Field label="Permissions" hint={PROFILE_TEXT[profile].hint} group>
            <Segmented value={profile} onChange={setProfile} options={(Object.keys(PROFILE_TEXT) as PermissionProfile[]).map((p) => ({ value: p, label: PROFILE_TEXT[p].label }))} />
          </Field>
        </div>

        <div className="rounded-xl border border-line p-4">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" className="accent-[var(--accent)]" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
            <CalendarClock className="size-4 text-muted" /> Run on a schedule
          </label>
          {scheduled && (
            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {PRESETS.map((p) => (
                  <button
                    key={p.cron}
                    type="button"
                    onClick={() => setCron(p.cron)}
                    className={"rounded-md border px-2 py-1 text-xs " + (cron === p.cron ? "border-accent bg-accent-soft text-accent-ink" : "border-line text-ink-2 hover:bg-surface-2")}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Cron expression" hint="minute hour day month weekday">
                  <Input value={cron} onChange={(e) => setCron(e.target.value)} className="font-mono" />
                </Field>
                <Field label="Time zone">
                  <Input value={tz} onChange={(e) => setTz(e.target.value)} list="tz-options" />
                  <datalist id="tz-options">
                    {["UTC", "Asia/Jerusalem", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"].map((z) => (
                      <option key={z} value={z} />
                    ))}
                  </datalist>
                </Field>
              </div>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-line p-4">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" className="accent-[var(--accent)]" checked={webhook} onChange={(e) => setWebhook(e.target.checked)} />
            <Webhook className="size-4 text-muted" /> Trigger from a webhook
          </label>
          {webhook && (
            <div className="mt-3 space-y-3">
              <p className="text-xs text-muted">
                Any system that can POST JSON can start this workflow: GitHub, Jira, Linear, Sentry, Zendesk, PagerDuty. The secret
                URL appears after you save.
              </p>
              <Field label="Only when (optional)" hint='JSON filter, e.g. {"path": "action", "equals": "opened"} or a list of them. "contains" also works.'>
                <Input value={filter} onChange={(e) => setFilter(e.target.value)} className="font-mono text-[13px]" placeholder='{"path": "action", "equals": "opened"}' />
              </Field>
              {filterError && <p className="text-xs text-bad">{filterError}</p>}
              {workflow?.webhook_enabled && (
                <Button type="button" size="sm" onClick={() => confirm("Create a new secret URL? The current one stops working.") && rotate.mutate()}>
                  Show a new webhook URL
                </Button>
              )}
            </div>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="accent-[var(--accent)]" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Enabled (paused workflows ignore schedules and webhooks)
        </label>

        <ErrorNote error={save.error ?? rotate.error} />
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            {workflow ? "Save" : "Create workflow"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function WebhookReady({ wf, onClose }: { wf: Workflow; onClose: () => void }) {
  const example = `curl -X POST ${wf.webhook_url} \\\n  -H 'Content-Type: application/json' \\\n  -d '{"action": "opened", "issue": {"title": "Checkout crashes on empty cart"}}'`;
  return (
    <Dialog open onClose={onClose} title="Webhook ready" width={620}>
      <p className="text-sm text-muted">
        This URL is the credential: anyone who has it can start <span className="font-medium text-ink">{wf.name}</span>. It is shown
        once. Paste it into the other system's webhook settings.
      </p>
      <div className="mt-4 flex items-center gap-2 rounded-lg bg-surface-2 p-2 pl-3">
        <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{wf.webhook_url}</code>
        <CopyButton text={wf.webhook_url ?? ""} />
      </div>
      <p className="mt-4 mb-2 text-xs font-medium tracking-wide text-muted uppercase">Try it</p>
      <pre className="overflow-x-auto rounded-lg bg-[#0d1729] p-3 font-mono text-[12px] text-[#e8ecf1]">{example}</pre>
      <div className="mt-5 flex justify-end">
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </div>
    </Dialog>
  );
}
