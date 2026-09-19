import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Database, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api } from "../../lib/api";
import type { AiDeveloper, Environment, EnvironmentPreset, Team } from "../../lib/types";
import { Dialog } from "../Dialog";
import { Button, ErrorNote, Field, Input } from "../ui";
import { Segmented, Textarea } from "../work";

/**
 * Hiring an AI developer in one pass: who it is, where it works, and what it works
 * against. The workbench is part of hiring on purpose — an agent with a database it can
 * migrate and query checks its own work, and that is the difference between a patch and
 * a change someone can ship.
 */
export function NewAiDeveloper({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [repo, setRepo] = useState("");
  const [vendor, setVendor] = useState<"claude-code" | "codex">("claude-code");
  const [instructions, setInstructions] = useState("");
  const [presetKey, setPresetKey] = useState("postgres");

  const presets = useQuery({
    queryKey: ["environment-presets"],
    queryFn: () => api<{ items: EnvironmentPreset[] }>("/api/environment-presets"),
    enabled: open,
  });
  const existing = useQuery({
    queryKey: ["environments"],
    queryFn: () => api<Environment[]>("/api/environments"),
    enabled: open,
  });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api<Team[]>("/api/teams"), enabled: open });

  const create = useMutation({
    mutationFn: async () => {
      // A workbench first (unless one with this name already exists), then the developer
      // that owns it: one form, so nobody has to know the word "environment" to start.
      let environment_id: string | null = null;
      const preset = (presets.data?.items ?? []).find((p) => p.key === presetKey);
      if (preset && preset.key !== "none") {
        const wanted = `${slug(name)}-${preset.environment.name}`.slice(0, 80);
        const already = (existing.data ?? []).find((e) => e.name === wanted);
        environment_id = already
          ? already.id
          : (
              await api<Environment>("/api/environments", {
                method: "POST",
                json: { ...preset.environment, name: wanted },
              })
            ).id;
      }
      return api<AiDeveloper>("/api/ai-developers", {
        method: "POST",
        json: {
          name: name.trim(),
          agent_vendor: vendor,
          default_repo: repo.trim() || null,
          instructions: instructions.trim() || null,
          environment_id,
          team_ids: (teams.data ?? []).slice(0, 1).map((t) => t.id),
        },
      });
    },
    onSuccess: (dev) => {
      qc.invalidateQueries({ queryKey: ["ai-developers"] });
      qc.invalidateQueries({ queryKey: ["environments"] });
      reset();
      onClose();
      navigate(`/ai/${dev.id}`);
    },
  });

  const reset = () => {
    setName("");
    setRepo("");
    setInstructions("");
    setPresetKey("postgres");
  };

  return (
    <Dialog open={open} onClose={onClose} title="Hire an AI developer" width={620}>
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" hint="How it appears everywhere: sessions, pull requests, Slack.">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada" required maxLength={120} autoFocus />
          </Field>
          <Field label="Repository" hint="host/owner/name. Where its work happens unless a task says otherwise.">
            <Input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="github.com/acme/api" maxLength={300} />
          </Field>
        </div>

        <Field label="Agent" group>
          <Segmented
            value={vendor}
            onChange={setVendor}
            options={[
              { value: "claude-code", label: "Claude Code" },
              { value: "codex", label: "Codex" },
            ]}
          />
        </Field>

        <Field
          label="Workbench"
          group
          hint="The services it develops against, kept between tasks like a person's own machine. You can change this later."
        >
          <div className="grid gap-2">
            {(presets.data?.items ?? []).map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => setPresetKey(p.key)}
                className={
                  "flex items-start gap-3 rounded-xl border p-3 text-left transition-colors " +
                  (presetKey === p.key ? "border-accent bg-accent-soft/40" : "border-line hover:bg-surface-2")
                }
              >
                <span
                  className={
                    "mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-lg " +
                    (presetKey === p.key ? "bg-accent text-white" : "bg-surface-2 text-muted")
                  }
                >
                  {presetKey === p.key ? <Check className="size-4" /> : <Database className="size-4" />}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{p.title}</span>
                  <span className="block text-[13px] leading-relaxed text-muted">{p.description}</span>
                </span>
              </button>
            ))}
          </div>
        </Field>

        <Field
          label="Standing instructions"
          hint="Optional. Added to the front of every task: conventions, what to test, when to stop and ask."
        >
          <Textarea
            rows={3}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder={"Follow the patterns in the module you are changing.\nAlways run the tests before opening a pull request."}
            maxLength={20000}
          />
        </Field>

        <ErrorNote error={create.error} />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted">Its sessions are owned by whoever assigns the work.</p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
              <Sparkles className="size-4" /> Hire <ArrowRight className="size-3.5" />
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "agent";
}
