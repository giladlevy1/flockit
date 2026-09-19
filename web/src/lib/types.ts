export type Role = "admin" | "lead" | "developer";
export type Outcome = "completed" | "abandoned" | "errored" | "unknown";
export type Status = "live" | "idle" | "ended";
export type Origin = "human" | "workflow";

export interface TeamRef {
  id: string;
  name: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  teams: TeamRef[];
  created_at: string;
  last_login_at: string | null;
  session_count: number;
  last_session_at: string | null;
}

export interface Me {
  user: User;
  org: { id: string; name: string };
  scope: "organisation" | "team" | "self";
}

export interface Session {
  id: string;
  owner: { id: string; name: string; email: string; teams: string[] };
  origin: Origin;
  agent_vendor: string;
  agent_version: string | null;
  agent_model: string | null;
  models_used: string[];
  repo: string | null;
  branch: string | null;
  task_ref: string | null;
  started_at: string;
  last_seen_at: string;
  ended_at: string | null;
  duration_seconds: number;
  status: Status;
  outcome: Outcome;
  end_reason: string | null;
  turn_count: number;
}

export interface SessionPage {
  items: Session[];
  total: number;
  limit: number;
  offset: number;
}

export interface Summary {
  sessions: number;
  people: number;
  repos: number;
  agent_hours: number;
  live_sessions: number;
  live_people: number;
  turns: number;
  outcomes: Record<Outcome, number>;
  by_agent: { vendor: string; model: string | null; sessions: number; hours: number; people: number }[];
  top_repos: { repo: string; sessions: number; hours: number; people: number; abandoned: number }[];
  overlaps: { task_ref: string; sessions: number; hours: number; people: string[]; last_seen_at: string }[];
  daily: { day: string; sessions: number; hours: number }[];
}

export interface Facets {
  people: { id: string; name: string; email: string }[];
  teams: { id: string; name: string }[];
  repos: string[];
  vendors: string[];
  models: string[];
}

export interface Team {
  id: string;
  name: string;
  member_ids: string[];
}

export interface Token {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ConnectInfo {
  server_url: string;
  public_url_configured: boolean;
  collector_available: boolean;
  collector_package: string | null;
  install_command: string;
}
