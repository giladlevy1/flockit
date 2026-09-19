import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../lib/api";
import type { Environment, EnvironmentPreset, Service } from "../../lib/types";
import { Dialog } from "../Dialog";
import { Badge, Button, Card, ErrorNote, Field, Input, Spinner } from "../ui";
import { Segmented, Select, Textarea } from "../work";

/**
 * Workbenches: the services AI developers develop against. This is deliberately close to
 * the metal — images, ports, variable names — because the people who set it up are the
 * people who run the real thing, and hiding it behind a wizard would only make them guess.
 */
export function Workbenches({ isAdmin }: { isAdmin: boolean }) {
  const [editing, setEditing] = useState<Environment | "new" | null>(null);
  const list = useQuery({ queryKey: ["environments"], queryFn: () => api<Environment[]>("/api/environments") });

  return (
    <>
      <div className="mt-10 mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Workbenches</h2>
          <p className="max-w-2xl text-sm text-muted">
            What an AI developer works against: a database with realistic data, a cache, a stand-in for one customer's
            account. Kept between tasks, so an agent can migrate, seed and query — and run the tests against something
            that behaves like production before anyone reviews its change.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setEditing("new")}>
            <Plus className="size-4" /> New workbench
          </Button>
        )}
      </div>

      <Card className="overflow-hidden">
        {list.isLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner />
          </div>
        ) : list.data?.length ? (
          <ul className="divide-y divide-line">
            {list.data.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <Database className="size-4 shrink-0 text-muted" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-medium">{e.name}</span>
                    <Badge tone={e.persistent ? "accent" : "neutral"}>{e.persistent ? "persistent" : "throwaway"}</Badge>
                    {e.used_by.map((u) => (
                      <Badge key={u.id}>{u.name}</Badge>
                    ))}
                  </div>
                  <div className="truncate text-xs text-muted">
                    {e.services.map((s) => `${s.name} (${s.image})`).join(" · ") || "no services"}
                  </div>
                </div>
                {isAdmin && (
                  <Button size="sm" variant="ghost" onClick={() => setEditing(e)}>
                    Edit
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-8 text-center text-sm text-muted">
            None yet. An AI developer without one can still write code; it just cannot run it against anything.
          </p>
        )}
      </Card>

      {editing && <WorkbenchDialog env={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

const BLANK: Service = { name: "db", image: "postgres:16-alpine", env: {}, port: 5432, url_env: "DATABASE_URL", url: "", ready: "", data_path: "" };

function WorkbenchDialog({ env, onClose }: { env: Environment | null; onClose: () => void }) {
  const qc = useQueryClient();
  const presets = useQuery({ queryKey: ["environment-presets"], queryFn: () => api<{ items: EnvironmentPreset[] }>("/api/environment-presets") });
  const [name, setName] = useState(env?.name ?? "");
  const [description, setDescription] = useState(env?.description ?? "");
  const [services, setServices] = useState<Service[]>(env?.services ?? []);
  const [variables, setVariables] = useState(pairsToText(env?.variables ?? {}));
  const [secrets, setSecrets] = useState((env?.secret_names ?? []).join(", "));
  const [setup, setSetup] = useState(env?.setup_script ?? "");
  const [persistent, setPersistent] = useState(env?.persistent ?? true);

  const body = () => ({
    name,
    description,
    services: services.map((s) => ({ ...s, env: s.env ?? {} })),
    variables: textToPairs(variables),
    secret_names: secrets.split(/[,\s]+/).filter(Boolean),
    setup_script: setup || null,
    persistent,
  });

  const save = useMutation({
    mutationFn: () =>
      env ? api(`/api/environments/${env.id}`, { method: "PUT", json: body() }) : api("/api/environments", { method: "POST", json: body() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["environments"] });
      qc.invalidateQueries({ queryKey: ["ai-developers"] });
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/environments/${env!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["environments"] });
      onClose();
    },
  });

  const applyPreset = (key: string) => {
    const preset = presets.data?.items.find((p) => p.key === key);
    if (!preset) return;
    setName((n) => n || preset.environment.name);
    setDescription(preset.environment.description);
    setServices(preset.environment.services);
    setVariables(pairsToText(preset.environment.variables));
    setSetup(preset.environment.setup_script ?? "");
    setPersistent(preset.environment.persistent);
  };

  return (
    <Dialog open onClose={onClose} title={env ? `Edit ${env.name}` : "New workbench"} width={680}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {!env && (
          <Field label="Start from" group hint="A starting point you can edit. Nothing here is fixed.">
            <Select defaultValue="" onChange={(e) => applyPreset(e.target.value)}>
              <option value="">Choose a starting point…</option>
              {(presets.data?.items ?? []).map((p) => (
                <option key={p.key} value={p.key}>
                  {p.title}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Name" hint="Lower-case letters, digits and dashes.">
            <Input value={name} onChange={(e) => setName(e.target.value)} required pattern="[a-z][a-z0-9\-]*" placeholder="app-postgres" />
          </Field>
          <Field label="Data" group hint="Persistent keeps the database between tasks, like a real machine.">
            <Segmented
              value={persistent ? "keep" : "fresh"}
              onChange={(v) => setPersistent(v === "keep")}
              options={[
                { value: "keep", label: "Persistent" },
                { value: "fresh", label: "Fresh each task" },
              ]}
            />
          </Field>
        </div>

        <Field label="What this is" hint="Shown on the AI developer's page. Say what data it holds and what it is for.">
          <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={8000} />
        </Field>

        <Field label="Services" group>
          <div className="space-y-2">
            {services.map((s, i) => (
              <div key={i} className="rounded-xl border border-line p-3">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <Input
                    value={s.name}
                    onChange={(e) => setServices(replace(services, i, { ...s, name: e.target.value }))}
                    placeholder="db"
                    aria-label="Service name"
                  />
                  <Input
                    value={s.image}
                    onChange={(e) => setServices(replace(services, i, { ...s, image: e.target.value }))}
                    placeholder="postgres:16-alpine"
                    aria-label="Image"
                  />
                  <Input
                    value={s.url_env ?? ""}
                    onChange={(e) => setServices(replace(services, i, { ...s, url_env: e.target.value }))}
                    placeholder="DATABASE_URL"
                    aria-label="Variable the agent reads"
                  />
                  <Input
                    value={s.url ?? ""}
                    onChange={(e) => setServices(replace(services, i, { ...s, url: e.target.value }))}
                    placeholder="postgresql://app:flockit@db:5432/app"
                    aria-label="Value of that variable"
                  />
                  <Input
                    value={s.ready ?? ""}
                    onChange={(e) => setServices(replace(services, i, { ...s, ready: e.target.value }))}
                    placeholder="pg_isready -U app"
                    aria-label="Readiness command"
                  />
                  <Input
                    value={s.data_path ?? ""}
                    onChange={(e) => setServices(replace(services, i, { ...s, data_path: e.target.value }))}
                    placeholder="/var/lib/postgresql/data"
                    aria-label="Where its data lives"
                  />
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <Input
                    value={pairsToText(s.env ?? {}, " ")}
                    onChange={(e) => setServices(replace(services, i, { ...s, env: textToPairs(e.target.value) }))}
                    placeholder="POSTGRES_PASSWORD=flockit POSTGRES_DB=app"
                    aria-label="Service environment"
                  />
                  <Button size="sm" variant="ghost" type="button" onClick={() => setServices(services.filter((_, j) => j !== i))}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            ))}
            <Button size="sm" type="button" onClick={() => setServices([...services, { ...BLANK, name: `svc${services.length + 1}` }])}>
              <Plus className="size-3.5" /> Add a service
            </Button>
          </div>
        </Field>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Variables" hint="KEY=value, one per line. Not for secrets.">
            <Textarea rows={2} value={variables} onChange={(e) => setVariables(e.target.value)} placeholder="CUSTOMER=acme" />
          </Field>
          <Field label="Secrets to pass through" hint="Names only. The runner supplies the values from its own environment.">
            <Input value={secrets} onChange={(e) => setSecrets(e.target.value.toUpperCase())} placeholder="STRIPE_TEST_KEY" />
          </Field>
        </div>

        <Field label="Setup script" hint="Runs once, the first time the data is created: migrations, fixtures, one customer's account.">
          <Textarea rows={3} value={setup} onChange={(e) => setSetup(e.target.value)} placeholder={'psql "$DATABASE_URL" -f db/schema.sql'} />
        </Field>

        <ErrorNote error={save.error || remove.error} />
        <div className="flex items-center justify-between gap-2">
          {env ? (
            <Button
              type="button"
              variant="danger"
              loading={remove.isPending}
              onClick={() => confirm(`Delete ${env.name}? Its data on the runners is removed separately.`) && remove.mutate()}
            >
              Delete
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              Save
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

function replace<T>(list: T[], index: number, value: T): T[] {
  return list.map((item, i) => (i === index ? value : item));
}

function pairsToText(pairs: Record<string, string>, join = "\n"): string {
  return Object.entries(pairs)
    .map(([k, v]) => `${k}=${v}`)
    .join(join);
}

function textToPairs(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split(/[\n]+/)) {
    for (const pair of line.trim().split(/\s+/)) {
      const at = pair.indexOf("=");
      if (at > 0) out[pair.slice(0, at)] = pair.slice(at + 1);
    }
  }
  return out;
}
