export type Role = "admin" | "lead" | "developer";
export type Outcome = "completed" | "abandoned" | "errored" | "unknown";
export type Status = "live" | "idle" | "ended";
export type Origin = "human" | "workflow";
export type DispatchMode = "off" | "ask" | "auto";
export type RunMode = "ask" | "auto";
export type PermissionProfile = "read_only" | "edit" | "full";
export type RunStatus = "offered" | "queued" | "starting" | "running" | "succeeded" | "failed" | "declined" | "cancelled";

export interface TeamRef {
  id: string;
  name: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  kind: "human" | "ai";
  dispatch_mode: DispatchMode;
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
  onboarded: boolean;
  slack_linked: boolean;
}

export interface Session {
  id: string;
  owner: { id: string; name: string; email: string; teams: string[] };
  actor: { id: string; name: string; kind: "human" | "ai" } | null;
  title: string | null;
  task: { id: string; title: string; status: RunStatus } | null;
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
  tokens_input: number;
  tokens_output: number;
  tokens_cache_read: number;
  tokens_cache_write: number;
  tool_calls: number;
  message_count: number;
  files_touched: number;
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
  tokens_input: number;
  tokens_output: number;
  tool_calls: number;
  ai_sessions: number;
  task_sessions: number;
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
  kind: "collector" | "mcp";
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ConnectInfo {
  server_url: string;
  server_url_source: "env" | "setup" | "request";
  collector_available: boolean;
  collector_package: string | null;
  install_command: string;
}

export interface PersonRef {
  id: string;
  name: string;
  kind: "human" | "ai";
}

export interface Task {
  id: string;
  title: string;
  prompt: string;
  repo: string | null;
  base_branch: string | null;
  branch: string | null;
  task_ref: string | null;
  status: RunStatus;
  mode: RunMode;
  permission_profile: PermissionProfile;
  interactive: boolean;
  trigger: string;
  assignee: PersonRef | null;
  triggered_by: PersonRef | null;
  workflow: { id: string; name: string } | null;
  machine: { id: string; name: string; kind: "laptop" | "runner" } | null;
  session_id: string | null;
  result: string | null;
  error: string | null;
  pr_url: string | null;
  cost_usd: number | null;
  created_at: string;
  updated_at: string;
  accepted_at: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface TaskPage {
  items: Task[];
  total: number;
  counts: Partial<Record<RunStatus, number>>;
}

export interface Machine {
  id: string;
  name: string;
  platform: string | null;
  version?: string | null;
  online: boolean;
  last_seen_at: string | null;
}

export interface Inbox {
  offered: number;
  active: number;
  dispatch_mode: DispatchMode;
  machines: Machine[];
}

export interface Workflow {
  id: string;
  name: string;
  description: string | null;
  prompt_template: string;
  repo: string;
  base_branch: string | null;
  assignee: PersonRef;
  mode: RunMode;
  permission_profile: PermissionProfile;
  schedule_cron: string | null;
  schedule_timezone: string;
  next_run_at: string | null;
  webhook_enabled: boolean;
  webhook_filter: unknown;
  enabled: boolean;
  created_at: string;
  last_run_at: string | null;
  runs: Partial<Record<RunStatus, number>>;
  webhook_url: string | null;
}

export interface Service {
  name: string;
  image: string;
  env: Record<string, string>;
  port: number | null;
  url_env: string | null;
  url: string | null;
  ready: string | null;
  data_path: string | null;
}

export interface Environment {
  id: string;
  name: string;
  description: string;
  services: Service[];
  variables: Record<string, string>;
  secret_names: string[];
  setup_script: string | null;
  persistent: boolean;
  created_at: string;
  updated_at: string;
  used_by: { id: string; name: string }[];
}

export interface EnvironmentPreset {
  key: string;
  title: string;
  description: string;
  environment: Omit<Environment, "id" | "created_at" | "updated_at" | "used_by">;
}

export interface AiDeveloperProfile {
  developer: AiDeveloper;
  expertise: { repos: { repo: string; tasks: number }[]; areas: { area: string; files: number }[] };
  tasks: {
    id: string;
    title: string;
    status: RunStatus;
    repo: string | null;
    task_ref: string | null;
    session_id: string | null;
    pr_url: string | null;
    cost_usd: number | null;
    created_at: string;
    ended_at: string | null;
  }[];
  sessions: {
    id: string;
    title: string | null;
    repo: string | null;
    started_at: string;
    ended_at: string | null;
    turns: number;
    files_touched: number;
  }[];
  workflows: { id: string; name: string; enabled: boolean; trigger: string; schedule_cron: string | null; repo: string }[];
}

export interface AiDeveloper {
  id: string;
  name: string;
  email: string;
  agent_vendor: "claude-code" | "codex";
  agent_model: string | null;
  runner_pool: string | null;
  sponsor: { id: string; name: string } | null;
  instructions: string | null;
  teams: TeamRef[];
  is_active: boolean;
  created_at: string;
  stats: { tasks: Partial<Record<RunStatus, number>>; tokens: number; cost_usd: number };
  current_task: { id: string; title: string; status: RunStatus } | null;
  environment: { id: string; name: string; description: string; services: Service[]; persistent: boolean } | null;
  default_repo: string | null;
}

export interface Runner {
  id: string;
  name: string;
  pool: string | null;
  token_prefix: string | null;
  platform: string | null;
  version: string | null;
  capabilities: Record<string, unknown> | null;
  capacity: number;
  online: boolean;
  last_seen_at: string | null;
  created_at: string;
  running: number;
  token?: string | null;
}

export interface TranscriptMessage {
  seq: number;
  role: "user" | "assistant";
  kind: "text" | "tool_use" | "tool_result";
  tool_name: string | null;
  content: string;
  at: string;
}

export interface SearchHit {
  session_id: string;
  seq: number;
  role: string;
  kind: string;
  tool_name: string | null;
  snippet: string;
  at: string;
  session: {
    title: string | null;
    repo: string | null;
    branch: string | null;
    owner: string;
    actor: string | null;
    agent_model: string | null;
  };
}

export interface AuditItem {
  id: number;
  actor: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}
