import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { KeyRound, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink } from "react-router";

import { api } from "../lib/api";
import { useTheme, type ThemeChoice } from "../lib/theme";
import type { Me } from "../lib/types";
import { Dialog } from "./Dialog";
import { Logo } from "./Logo";
import { Avatar, Button, ErrorNote, Field, Input } from "./ui";

const NAV = [
  { to: "/", label: "Sessions", end: true },
  { to: "/people", label: "People" },
  { to: "/connect", label: "Connect" },
];

export function Layout({ me, children }: { me: Me; children: ReactNode }) {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-6 px-4 sm:px-6">
          <NavLink to="/" aria-label="Flockit home">
            <Logo />
          </NavLink>
          <nav className="flex items-center gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    "rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors",
                    isActive ? "bg-surface-2 text-ink" : "text-muted hover:text-ink",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-muted md:inline">{me.org.name}</span>
            <UserMenu me={me} />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </div>
  );
}

function UserMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const qc = useQueryClient();
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => root.current && !root.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" });
    qc.setQueryData(["me"], null);
    qc.clear();
    window.location.href = "/login";
  };

  const themes: { value: ThemeChoice; icon: ReactNode; label: string }[] = [
    { value: "light", icon: <Sun className="size-3.5" />, label: "Light" },
    { value: "dark", icon: <Moon className="size-3.5" />, label: "Dark" },
    { value: "system", icon: <Monitor className="size-3.5" />, label: "System" },
  ];

  return (
    <div ref={root} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full p-0.5 hover:ring-2 hover:ring-line"
        aria-label="Account menu"
        aria-expanded={open}
      >
        <Avatar name={me.user.name} id={me.user.id} size={30} />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-64 rounded-xl border border-line bg-surface p-1.5 shadow-xl">
          <div className="px-2.5 py-2">
            <div className="truncate text-sm font-medium">{me.user.name}</div>
            <div className="truncate text-xs text-muted">{me.user.email}</div>
            <div className="mt-1.5 text-xs text-muted">
              <span className="capitalize">{me.user.role}</span> · sees{" "}
              {me.scope === "organisation" ? "the whole organisation" : me.scope === "team" ? "their teams" : "own sessions"}
            </div>
          </div>
          <div className="my-1 h-px bg-line" />
          <div className="flex gap-1 px-1.5 py-1">
            {themes.map((t) => (
              <button
                key={t.value}
                onClick={() => setTheme(t.value)}
                className={clsx(
                  "flex flex-1 items-center justify-center gap-1 rounded-md py-1.5 text-xs",
                  theme === t.value ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink",
                )}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>
          <div className="my-1 h-px bg-line" />
          <button
            onClick={() => {
              setPwOpen(true);
              setOpen(false);
            }}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2"
          >
            <KeyRound className="size-4 text-muted" /> Change password
          </button>
          <button onClick={logout} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2">
            <LogOut className="size-4 text-muted" /> Sign out
          </button>
        </div>
      )}
      <PasswordDialog open={pwOpen} onClose={() => setPwOpen(false)} />
    </div>
  );
}

function PasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () => api("/api/auth/password", { method: "POST", json: { current_password: current, new_password: next } }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      onClose();
    },
  });
  return (
    <Dialog open={open} onClose={onClose} title="Change password">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          change.mutate();
        }}
      >
        <Field label="Current password">
          <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </Field>
        <Field label="New password" hint="At least 8 characters.">
          <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} />
        </Field>
        <ErrorNote error={change.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={change.isPending}>
            Update password
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
