import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { api } from "../../lib/api";
import type { AiDeveloper, Facets, Me, PermissionProfile, RunMode, Task, User } from "../../lib/types";
import { Dialog } from "../Dialog";
import { Button, ErrorNote, Field, Input } from "../ui";
import { PROFILE_TEXT, Segmented, Select, Textarea } from "../work";

export function useAssignees(me: Me) {
  const people = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/api/users"),
    enabled: me.user.role !== "developer",
  });
  const ai = useQuery({ queryKey: ["ai-developers"], queryFn: () => api<AiDeveloper[]>("/api/ai-developers") });
  return useMemo(() => {
    const humans = (me.user.role === "developer" ? [me.user] : people.data ?? [me.user]).filter((u) => u.is_active);
    const bots = (ai.data ?? []).filter((a) => a.is_active);
    return { humans, bots };
  }, [me.user, people.data, ai.data]);
}

export function NewTaskDialog({
  me,
  open,
  onClose,
  initial,
}: {
  me: Me;
  open: boolean;
  onClose: () => void;
  initial?: Partial<{ title: string; prompt: string; repo: string; task_ref: string; assignee_id: string }>;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { humans, bots } = useAssignees(me);
  const facets = useQuery({ queryKey: ["facets"], queryFn: () => api<Facets>("/api/sessions/facets") });
  const [title, setTitle] = useState(initial?.title ?? "");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [repo, setRepo] = useState(initial?.repo ?? "");
  const [baseBranch, setBaseBranch] = useState("");
  const [taskRef, setTaskRef] = useState(initial?.task_ref ?? "");
  const [assignee, setAssignee] = useState(initial?.assignee_id ?? me.user.id);
  const [mode, setMode] = useState<RunMode>("ask");
  const [profile, setProfile] = useState<PermissionProfile>("edit");
  const isBot = bots.some((b) => b.id === assignee);

  const create = useMutation({
    mutationFn: () =>
      api<Task>("/api/tasks", {
        method: "POST",
        json: {
          title,
          prompt,
          repo: repo || null,
          base_branch: baseBranch || null,
          task_ref: taskRef || null,
          assignee_id: assignee,
          mode,
          permission_profile: profile,
        },
      }),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["inbox"] });
      onClose();
      navigate(`/tasks?task=${t.id}`);
    },
  });

  return (
    <Dialog open={open} onClose={onClose} title="New task" width={620}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Fix the flaky checkout test" required autoFocus />
        </Field>
        <Field label="What should the agent do?" hint="This is the prompt Claude Code (or Codex) starts with. Be specific about the outcome.">
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={6}
            required
            placeholder={"tests/checkout.spec.ts fails about 1 in 10 runs on CI.\nFind the race, fix it, and add a regression test."}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Repository" hint={isBot ? "Required for AI developers." : "Where the work happens."}>
            <Input value={repo} onChange={(e) => setRepo(e.target.value)} list="repo-options" placeholder="github.com/acme/api" required={isBot} />
            <datalist id="repo-options">
              {facets.data?.repos.map((r) => <option key={r} value={r} />)}
            </datalist>
          </Field>
          <Field label="Base branch" hint="Leave empty for the default branch.">
            <Input value={baseBranch} onChange={(e) => setBaseBranch(e.target.value)} placeholder="main" />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Assign to">
            <Select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <optgroup label="People">
                {humans.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.id === me.user.id ? `${u.name} (me)` : u.name}
                  </option>
                ))}
              </optgroup>
              {bots.length > 0 && (
                <optgroup label="AI developers">
                  {bots.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name} · {b.agent_vendor === "codex" ? "Codex" : "Claude Code"}
                    </option>
                  ))}
                </optgroup>
              )}
            </Select>
          </Field>
          <Field label="Ticket (optional)">
            <Input value={taskRef} onChange={(e) => setTaskRef(e.target.value)} placeholder="ENG-123 or an issue URL" />
          </Field>
        </div>
        {!isBot && (
          <Field
            label="How it starts"
            hint={
              mode === "ask"
                ? "The assignee accepts it first. Claude Code then opens in a terminal on their machine."
                : "Starts in the background on their machine without asking, if they allow auto-start. Otherwise they are asked."
            }
          >
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: "ask", label: "Ask the assignee" },
                { value: "auto", label: "Auto-start" },
              ]}
            />
          </Field>
        )}
        <Field label="Permissions" hint={PROFILE_TEXT[profile].hint}>
          <Segmented
            value={profile}
            onChange={setProfile}
            options={(Object.keys(PROFILE_TEXT) as PermissionProfile[]).map((p) => ({ value: p, label: PROFILE_TEXT[p].label }))}
          />
        </Field>
        <ErrorNote error={create.error} />
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            {isBot ? "Assign to AI developer" : assignee === me.user.id ? "Create task" : "Send task"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
