import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { AuthShell } from "../components/AuthShell";
import { Button, ErrorNote, Field, Input } from "../components/ui";
import { api } from "../lib/api";

export function SetupPage() {
  const [form, setForm] = useState({ org_name: "", name: "", email: "", password: "" });
  const qc = useQueryClient();
  const navigate = useNavigate();
  const setup = useMutation({
    mutationFn: () => api("/api/setup", { method: "POST", json: form }),
    onSuccess: async () => {
      qc.setQueryData(["setup"], { needs_setup: false });
      await qc.invalidateQueries({ queryKey: ["me"] });
      navigate("/connect", { replace: true });
    },
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <AuthShell title="Set up Flockit" sub="Create your organisation and the first admin account. Four minutes from here to an agent working on a real ticket.">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setup.mutate();
        }}
      >
        <Field label="Organisation">
          <Input value={form.org_name} onChange={set("org_name")} placeholder="Acme Engineering" required autoFocus />
        </Field>
        <Field label="Your name">
          <Input value={form.name} onChange={set("name")} placeholder="Maya Cohen" autoComplete="name" required />
        </Field>
        <Field label="Work email">
          <Input type="email" value={form.email} onChange={set("email")} placeholder="maya@acme.dev" autoComplete="email" required />
        </Field>
        <Field label="Password" hint="At least 8 characters. Stored as an Argon2 hash in your own database.">
          <Input type="password" value={form.password} onChange={set("password")} autoComplete="new-password" minLength={8} required />
        </Field>
        <ErrorNote error={setup.error} />
        <Button type="submit" variant="primary" className="w-full" loading={setup.isPending}>
          Create organisation
        </Button>
      </form>
    </AuthShell>
  );
}
