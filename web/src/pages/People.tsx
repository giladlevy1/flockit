import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Pencil, Plus, Trash2, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { Dialog } from "../components/Dialog";
import { Avatar, Badge, Button, Card, CopyButton, ErrorNote, Field, Input, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { relativeTime } from "../lib/format";
import type { Me, Role, Team, User } from "../lib/types";

const ROLE_TEXT: Record<Role, string> = {
  admin: "Sees the whole organisation and manages people",
  lead: "Sees everyone on their teams",
  developer: "Sees their own sessions",
};

function generatePassword(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => "abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789"[b % 55]).join("");
}

export function PeoplePage({ me }: { me: Me }) {
  const isAdmin = me.user.role === "admin";
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/api/users") });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api<Team[]>("/api/teams") });
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [editingTeam, setEditingTeam] = useState<Team | "new" | null>(null);

  return (
    <div>
      <PageHeader
        title="People"
        sub={
          isAdmin
            ? "Everyone who can sign in, and the teams that decide what leads can see."
            : "The people whose sessions you can see."
        }
        actions={
          isAdmin && (
            <>
              <Button onClick={() => setEditingTeam("new")}>
                <Users className="size-4" /> New team
              </Button>
              <Button variant="primary" onClick={() => setEditing("new")}>
                <UserPlus className="size-4" /> Add person
              </Button>
            </>
          )
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Card className="overflow-hidden">
          {users.isLoading ? (
            <div className="flex h-40 items-center justify-center text-muted">
              <Spinner />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="border-b border-line bg-surface-2/60">
                  <tr className="text-left text-[11.5px] tracking-wide text-muted uppercase">
                    <th className="py-2.5 pr-3 pl-4 font-medium">Person</th>
                    <th className="px-3 py-2.5 font-medium">Role</th>
                    <th className="px-3 py-2.5 font-medium">Teams</th>
                    <th className="px-3 py-2.5 text-right font-medium">Sessions</th>
                    <th className="px-3 py-2.5 font-medium">Last session</th>
                    {isAdmin && <th className="py-2.5 pr-4 pl-3" />}
                  </tr>
                </thead>
                <tbody>
                  {users.data?.map((u) => (
                    <tr key={u.id} className={clsx("border-b border-line last:border-b-0", !u.is_active && "opacity-55")}>
                      <td className="py-2.5 pr-3 pl-4">
                        <div className="flex items-center gap-2.5">
                          <Avatar name={u.name} id={u.id} />
                          <div className="min-w-0">
                            <div className="truncate font-medium">
                              {u.name} {u.id === me.user.id && <span className="font-normal text-muted">(you)</span>}
                            </div>
                            <div className="truncate text-xs text-muted">{u.email}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="capitalize">{u.role}</span>
                        {!u.is_active && (
                          <Badge tone="bad" className="ml-2">
                            Deactivated
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {u.teams.length ? u.teams.map((t) => <Badge key={t.id}>{t.name}</Badge>) : <span className="text-muted">—</span>}
                        </div>
                      </td>
                      <td className="tabular px-3 py-2.5 text-right">
                        {u.session_count ? (
                          <Link to={`/?owner=${u.id}&range=all`} className="text-accent-ink hover:underline">
                            {u.session_count.toLocaleString()}
                          </Link>
                        ) : (
                          <span className="text-muted">0</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-ink-2">
                        {u.last_session_at ? relativeTime(u.last_session_at) : <span className="text-muted">Not connected</span>}
                      </td>
                      {isAdmin && (
                        <td className="py-2.5 pr-4 pl-3 text-right">
                          <Button size="sm" variant="ghost" onClick={() => setEditing(u)} aria-label={`Edit ${u.name}`}>
                            <Pencil className="size-3.5" />
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Teams</h2>
            {isAdmin && (
              <Button size="sm" variant="ghost" onClick={() => setEditingTeam("new")}>
                <Plus className="size-3.5" /> Add
              </Button>
            )}
          </div>
          <div className="space-y-2.5">
            {teams.data?.length === 0 && (
              <Card className="p-4 text-sm text-muted">
                {isAdmin
                  ? "No teams yet. A lead sees the sessions of everyone who shares a team with them."
                  : "You are not on a team."}
              </Card>
            )}
            {teams.data?.map((t) => (
              <TeamCard key={t.id} team={t} users={users.data ?? []} onEdit={isAdmin ? () => setEditingTeam(t) : undefined} />
            ))}
          </div>
          <Card className="mt-6 p-4">
            <h3 className="text-sm font-semibold">Roles</h3>
            <dl className="mt-2 space-y-2 text-sm">
              {(Object.keys(ROLE_TEXT) as Role[]).map((r) => (
                <div key={r}>
                  <dt className="font-medium capitalize">{r}</dt>
                  <dd className="text-muted">{ROLE_TEXT[r]}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>

      {isAdmin && editing && (
        <UserDialog user={editing === "new" ? null : editing} teams={teams.data ?? []} onClose={() => setEditing(null)} />
      )}
      {isAdmin && editingTeam && (
        <TeamDialog team={editingTeam === "new" ? null : editingTeam} users={users.data ?? []} onClose={() => setEditingTeam(null)} />
      )}
    </div>
  );
}

function TeamCard({ team, users, onEdit }: { team: Team; users: User[]; onEdit?: () => void }) {
  const members = users.filter((u) => team.member_ids.includes(u.id));
  const leads = members.filter((m) => m.role === "lead");
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{team.name}</div>
          <div className="text-xs text-muted">
            {team.member_ids.length} {team.member_ids.length === 1 ? "member" : "members"}
            {leads.length > 0 && ` · led by ${leads.map((l) => l.name.split(" ")[0]).join(", ")}`}
          </div>
        </div>
        {onEdit && (
          <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Edit ${team.name}`}>
            <Pencil className="size-3.5" />
          </Button>
        )}
      </div>
      {members.length > 0 && (
        <div className="mt-3 flex -space-x-1.5">
          {members.slice(0, 10).map((m) => (
            <span key={m.id} className="rounded-full ring-2 ring-surface" title={m.name}>
              <Avatar name={m.name} id={m.id} size={24} />
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function Checklist({ items, value, onChange }: { items: { id: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="max-h-52 overflow-y-auto rounded-lg border border-line p-1">
      {items.length === 0 && <p className="px-2 py-1.5 text-sm text-muted">Nothing here yet.</p>}
      {items.map((i) => (
        <label key={i.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2">
          <input
            type="checkbox"
            className="accent-[var(--accent)]"
            checked={value.includes(i.id)}
            onChange={(e) => onChange(e.target.checked ? [...value, i.id] : value.filter((v) => v !== i.id))}
          />
          {i.label}
        </label>
      ))}
    </div>
  );
}

function UserDialog({ user, teams, onClose }: { user: User | null; teams: Team[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "developer");
  const [teamIds, setTeamIds] = useState<string[]>(user?.teams.map((t) => t.id) ?? []);
  const [password, setPassword] = useState(user ? "" : generatePassword());
  const [done, setDone] = useState<{ email: string; password: string } | null>(null);

  const save = useMutation({
    mutationFn: () =>
      user
        ? api<User>(`/api/users/${user.id}`, {
            method: "PATCH",
            json: { name, role, team_ids: teamIds, ...(password ? { password } : {}) },
          })
        : api<User>("/api/users", { method: "POST", json: { name, email, role, team_ids: teamIds, password } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: ["teams"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
      if (!user || password) setDone({ email: user?.email ?? email, password });
      else onClose();
    },
  });
  const toggleActive = useMutation({
    mutationFn: () => api(`/api/users/${user!.id}`, { method: "PATCH", json: { is_active: !user!.is_active } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });

  if (done) {
    const signIn = `${window.location.origin}/login`;
    const message = `You have a Flockit account.\nSign in at ${signIn}\nEmail: ${done.email}\nTemporary password: ${done.password}\nThen open Connect to install the collector.`;
    return (
      <Dialog open onClose={onClose} title={user ? "Password reset" : "Person added"}>
        <p className="text-sm text-muted">Share these details with them directly. The password is not shown again.</p>
        <pre className="mt-4 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-[12.5px] leading-relaxed">{message}</pre>
        <div className="mt-4 flex justify-end gap-2">
          <CopyButton text={message} label="Copy message" />
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog open onClose={onClose} title={user ? `Edit ${user.name}` : "Add a person"} width={480}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </Field>
          <Field label="Email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={!!user} />
          </Field>
        </div>
        <Field label="Role" hint={ROLE_TEXT[role]}>
          <div className="grid grid-cols-3 gap-1 rounded-lg border border-line p-1">
            {(["developer", "lead", "admin"] as Role[]).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRole(r)}
                className={clsx(
                  "rounded-md py-1.5 text-sm capitalize",
                  role === r ? "bg-ink font-medium text-bg" : "text-muted hover:text-ink",
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Teams">
          <Checklist items={teams.map((t) => ({ id: t.id, label: t.name }))} value={teamIds} onChange={setTeamIds} />
        </Field>
        <Field label={user ? "Reset password" : "Temporary password"} hint={user ? "Leave empty to keep the current password." : "They can change it after signing in."}>
          <div className="flex gap-2">
            <Input value={password} onChange={(e) => setPassword(e.target.value)} minLength={user ? 0 : 8} className="font-mono" />
            <Button type="button" onClick={() => setPassword(generatePassword())}>
              Generate
            </Button>
          </div>
        </Field>
        <ErrorNote error={save.error ?? toggleActive.error} />
        <div className="flex items-center justify-between gap-2 pt-1">
          {user ? (
            <Button type="button" variant={user.is_active ? "danger" : "secondary"} onClick={() => toggleActive.mutate()} loading={toggleActive.isPending}>
              {user.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              {user ? "Save" : "Add person"}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

function TeamDialog({ team, users, onClose }: { team: Team | null; users: User[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(team?.name ?? "");
  const [members, setMembers] = useState<string[]>(team?.member_ids ?? []);
  const items = useMemo(
    () => users.filter((u) => u.is_active).map((u) => ({ id: u.id, label: `${u.name} · ${u.role}` })),
    [users],
  );
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["teams"] });
    qc.invalidateQueries({ queryKey: ["users"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
  };
  const save = useMutation({
    mutationFn: () =>
      team
        ? api(`/api/teams/${team.id}`, { method: "PATCH", json: { name, member_ids: members } })
        : api("/api/teams", { method: "POST", json: { name, member_ids: members } }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/teams/${team!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });

  return (
    <Dialog open onClose={onClose} title={team ? `Edit ${team.name}` : "New team"}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="Platform" />
        </Field>
        <Field label="Members" hint="Leads on this team see every member's sessions.">
          <Checklist items={items} value={members} onChange={setMembers} />
        </Field>
        <ErrorNote error={save.error ?? remove.error} />
        <div className="flex items-center justify-between pt-1">
          {team ? (
            <Button
              type="button"
              variant="danger"
              onClick={() => confirm(`Delete the ${team.name} team? People stay; only the grouping goes.`) && remove.mutate()}
              loading={remove.isPending}
            >
              <Trash2 className="size-3.5" /> Delete
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              {team ? "Save" : "Create team"}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}
