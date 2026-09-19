import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { AuthShell } from "../components/AuthShell";
import { Button, ErrorNote, Field, Input } from "../components/ui";
import { api } from "../lib/api";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";

  const login = useMutation({
    mutationFn: () => api("/api/auth/login", { method: "POST", json: { email, password } }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["me"] });
      navigate(safeNext, { replace: true });
    },
  });

  return (
    <AuthShell title="Sign in" sub="Your organisation's Flockit, on your own server.">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
      >
        <Field label="Email">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required autoFocus />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        <ErrorNote error={login.error} />
        <Button type="submit" variant="primary" className="w-full" loading={login.isPending}>
          Sign in
        </Button>
        <p className="text-center text-xs text-muted">Forgot your password? Ask an admin to reset it on the People page.</p>
      </form>
    </AuthShell>
  );
}
