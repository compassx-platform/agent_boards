export type Status =
  | 'backlog'
  | 'queued'
  | 'host_provisioning'
  | 'executing'
  | 'verifying'
  | 'needs_review'
  | 'done'
  | 'rejected'
  | 'blocked'

export type Priority = 'low' | 'normal' | 'high' | 'urgent'
export type RiskTier = 'low' | 'medium' | 'high'
export type PlanStatus =
  | 'none'
  | 'planning'
  | 'awaiting_approval'
  | 'approved'
  | 'implementing'
  | 'done'
  | 'failed'
export type CheckType =
  | 'automated_test'
  | 'schema_check'
  | 'output_match'
  | 'human_approval'
  | 'manual_checklist'

export interface Criterion {
  id: string
  description: string
  check_type: CheckType
  check_config: Record<string, unknown>
  result: string | null
  detail: string | null
}

export interface ContextRef {
  id: string
  type: 'link' | 'file' | 'dataset' | 'prior_task_output'
  ref: string
  description: string | null
}

export interface Attempt {
  id: string
  attempt_number: number
  execution_id: string | null
  phase: string
  pr_url: string | null
  status: string
  started_at: string | null
  finished_at: string | null
  agent_output: string | null
  verification_result: string | null
  verification_details: string | null
  failure_reason: string | null
  tools_used: string[]
  logs_ref: string | null
}

export interface TaskSession {
  id: string
  attempt_id: string | null
  provider: string
  session_id: string
  link: string | null
  status: string | null
  archived: boolean
  created_at: string
}

export interface Audit {
  id: string
  ts: string
  actor: string
  action: string
  from_status: string | null
  to_status: string | null
  reason: string | null
}

export interface Task {
  id: string
  title: string
  intent: string
  priority: Priority
  risk_tier: RiskTier
  status: Status
  created_by: string
  agent_capability: string
  harness: string
  workspace: string | null
  compassx_app_id: string | null
  compassx_app_name: string | null
  compassx_workspace_id: string | null
  compassx_workspace_name: string | null
  compassx_published: boolean
  host_id: string | null
  host_name: string | null
  dev_url: string | null
  provisioning_steps: ProvisionStep[]
  current_attempt: number
  max_attempts: number
  escalation_reason: string | null
  plan_required: boolean
  plan_status: PlanStatus
  plan_text: string | null
  bypass_verification: boolean
  verification_bypass_outcome: string
  pr_url: string | null
  session_id: string | null
  session_link: string | null
  session_provider: string | null
  session_status: string | null
  depends_on: string[]
  created_at: string
  updated_at: string
  criteria: Criterion[]
  context: ContextRef[]
  attempts: Attempt[]
  sessions: TaskSession[]
}

export interface Metrics {
  total: number
  by_status: Record<Status, number>
  escalation_count: number
  avg_attempts: number | null
  capability_failures: Record<string, number>
  adapter?: string
  harness?: string
}

export interface TaskCreateInput {
  title: string
  intent?: string
  priority: Priority
  risk_tier: RiskTier
  agent_capability: string
  max_attempts?: number
  plan_required?: boolean
  bypass_verification?: boolean
  verification_bypass_outcome?: string
  workspace?: string
  harness?: string
  compassx_app_id?: string
  compassx_app_name?: string
  compassx_workspace_id?: string
  context?: { type: string; ref: string; description?: string }[]
  criteria: { description: string; check_type: CheckType; check_config: Record<string, unknown> }[]
  depends_on?: string[]
}

export interface HarnessInfo {
  name: string
  agents: { id: string; name: string }[]
}

export interface HarnessesResponse {
  harnesses: HarnessInfo[]
  default: string
  adapter: string
  source: string
}

export type SettingDefType = 'string' | 'number' | 'bool'

export interface SettingDef {
  label: string
  type: SettingDefType
  min?: number
  max?: number
  step?: number
  options?: string[]
  description?: string
}

export interface SettingsResponse {
  settings: Record<string, unknown>
  definitions: Record<string, SettingDef>
}

export interface CompassXApp {
  id: string
  name: string
  slug: string
  description: string | null
  app_type: string
  status: string
  route: string | null
  git_repo_url: string | null
  git_branch: string | null
  created_at: string | null
}

export interface CompassXWorkspace {
  id: string
  name: string
  folder_path: string
  git_branch: string | null
  status: string
  created_at: string | null
  last_active_at: string | null
}

export interface CompassXAppsResponse {
  apps: CompassXApp[]
  error: string | null
  configured: boolean
}

export interface CompassXWorkspacesResponse {
  workspaces: CompassXWorkspace[]
  error: string | null
}

export interface CompassXDevStatusResponse {
  dev: Record<string, unknown>
  error?: string | null
}

export type ProvisionStepStatus = 'pending' | 'running' | 'done' | 'failed'

export interface ProvisionStep {
  name: string
  status: ProvisionStepStatus
  detail: string
  updated_at: string
}

export const PROVISION_STEP_LABELS: Record<string, string> = {
  resolve_workspace: 'Resolve dev workspace',
  start_dev: 'Start dev sandbox',
  wait_host_ready: 'Wait for dev host online',
  verify_omnigent: 'Verify host on Omnigent',
  create_session: 'Create agent session',
}

export const DEFAULT_HARNESS = 'omnigent'

const BASE = '/api/v1'

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  listTasks: (filters?: Record<string, string>) =>
    http<Task[]>('/tasks' + (filters ? `?${new URLSearchParams(filters)}` : '')),
  getTask: (id: string) => http<Task>(`/tasks/${id}`),
  audit: (id: string) => http<Audit[]>(`/tasks/${id}/audit`),
  createTask: (input: TaskCreateInput) =>
    http<Task>('/tasks', { method: 'POST', body: JSON.stringify(input) }),
  review: (id: string, action: 'approve' | 'retry' | 'reject' | 'approve_plan', note: string) =>
    http<Task>(`/tasks/${id}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, note }),
    }),
  unblock: (id: string) => http<Task>(`/tasks/${id}/unblock`, { method: 'POST' }),
  newSession: (id: string) => http<Task>(`/tasks/${id}/new_session`, { method: 'POST' }),
  approveExecution: (id: string, note: string) =>
    http<Task>(`/tasks/${id}/approve_execution`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  reviews: () => http<Task[]>('/reviews'),
  metrics: () => http<Metrics>('/metrics'),
  capabilities: () =>
    http<{ name: string; adapter: string }[]>('/capabilities'),
  harnesses: () => http<HarnessesResponse>('/harnesses'),
  settings: () => http<SettingsResponse>('/settings'),
  updateSettings: (settings: Record<string, unknown>) =>
    http<SettingsResponse>('/settings', {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    }),
  compassxApps: () => http<CompassXAppsResponse>('/compassx/apps'),
  compassxWorkspaces: (appId: string) =>
    http<CompassXWorkspacesResponse>(`/compassx/apps/${appId}/dev/workspaces`),
  compassxCreateWorkspace: (appId: string, name: string, gitBranch?: string) =>
    http<{ workspace: Record<string, unknown>; error: string | null }>(
      `/compassx/apps/${appId}/dev/workspaces`,
      { method: 'POST', body: JSON.stringify({ name, git_branch: gitBranch ?? 'main' }) },
    ),
  compassxDevStatus: (appId: string) =>
    http<CompassXDevStatusResponse>(`/compassx/apps/${appId}/dev/status`),
  parse: (text: string) =>
    http<{ parsed: Partial<TaskCreateInput>; confidence: number; note: string }>('/parse', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  seed: () => http<{ created: number }>('/demo/seed', { method: 'POST' }),
  omnigentSessions: (opts?: {
    kind?: string
    search_query?: string
    sort_by?: string
    order?: string
    limit?: number
    include_archived?: boolean
  }) => {
    const params = new URLSearchParams()
    if (opts?.kind) params.set('kind', opts.kind)
    if (opts?.search_query) params.set('search_query', opts.search_query)
    if (opts?.sort_by) params.set('sort_by', opts.sort_by)
    if (opts?.order) params.set('order', opts.order)
    if (opts?.limit != null) params.set('limit', String(opts.limit))
    if (opts?.include_archived) params.set('include_archived', 'true')
    const qs = params.toString()
    return http<OmnigentListResponse>('/omnigent/sessions' + (qs ? `?${qs}` : ''))
  },
  omnigentCreateSession: (payload: {
    agent_id: string
    title?: string
    workspace?: string
    host_id?: string
    model?: string
    reasoning_effort?: string
    initial_message?: string
    git?: { branch_name?: string; base_branch?: string }
    [key: string]: unknown
  }) =>
    http<OmnigentSessionResponse>('/omnigent/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  omnigentSession: (id: string) =>
    http<OmnigentSessionResponse>(`/omnigent/sessions/${encodeURIComponent(id)}`),
  omnigentUpdateSession: (id: string, payload: { title?: string; archived?: boolean; labels?: Record<string, unknown> }) =>
    http<OmnigentSessionResponse>(`/omnigent/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  omnigentDeleteSession: (id: string) =>
    http<{ source: string; success: boolean; error: string | null }>(`/omnigent/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  omnigentAutoTitle: (id: string) =>
    http<{ source: string; result: { title?: string } | null; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/auto-title`,
      { method: 'POST' },
    ),
  omnigentForkSession: (id: string, payload: { agent_id?: string; title?: string }) =>
    http<OmnigentSessionResponse>(`/omnigent/sessions/${encodeURIComponent(id)}/fork`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  omnigentSendEvent: (id: string, event: { type: string; data?: Record<string, unknown> }) =>
    http<{ source: string; response: unknown; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/events`,
      {
        method: 'POST',
        body: JSON.stringify(event),
      },
    ),
  omnigentSendMessage: (id: string, text: string) =>
    http<{ source: string; response: unknown; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/events`,
      {
        method: 'POST',
        body: JSON.stringify({
          type: 'message',
          data: {
            role: 'user',
            content: [{ type: 'input_text', text }],
          },
        }),
      },
    ),
  omnigentInterrupt: (id: string) =>
    http<{ source: string; response: unknown; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/events`,
      {
        method: 'POST',
        body: JSON.stringify({
          type: 'interrupt',
          data: {},
        }),
      },
    ),
  omnigentResolveElicitation: (id: string, elicitationId: string, value: unknown) =>
    http<{ source: string; response: unknown; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/events`,
      {
        method: 'POST',
        body: JSON.stringify({
          type: 'external_elicitation_resolved',
          data: {
            elicitation_id: elicitationId,
            response: value,
          },
        }),
      },
    ),
  omnigentSessionItems: (id: string) =>
    http<OmnigentItemsResponse>(`/omnigent/sessions/${encodeURIComponent(id)}/items`),
  omnigentEnvironments: (id: string) =>
    http<{ source: string; environments: OmnigentEnvironment[]; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/environments`,
    ),
  omnigentFilesystem: (id: string, envId: string, path: string = '') =>
    http<{ source: string; data: OmnigentFilesystemResponse | null; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/environments/${encodeURIComponent(envId)}/filesystem?path=${encodeURIComponent(path)}`,
    ),
  omnigentEnvironmentChanges: (id: string, envId: string) =>
    http<{ source: string; changes: OmnigentChangeEntry[]; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/environments/${encodeURIComponent(envId)}/changes`,
    ),
  omnigentEnvironmentSearch: (id: string, envId: string, q: string) =>
    http<{ source: string; results: OmnigentChangeEntry[]; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/environments/${encodeURIComponent(envId)}/search?q=${encodeURIComponent(q)}`,
    ),
  omnigentTerminals: (id: string) =>
    http<{ source: string; terminals: OmnigentTerminal[]; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/terminals`,
    ),
  omnigentCreateTerminal: (id: string, payload?: { terminal_name?: string; session_key?: string }) =>
    http<{ source: string; terminal: OmnigentTerminal | null; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/terminals`,
      {
        method: 'POST',
        body: JSON.stringify(payload ?? {}),
      },
    ),
  omnigentDeleteTerminal: (id: string, terminalId: string) =>
    http<{ source: string; success: boolean; error: string | null }>(
      `/omnigent/sessions/${encodeURIComponent(id)}/terminals/${encodeURIComponent(terminalId)}`,
      { method: 'DELETE' },
    ),
  omnigentAgents: () =>
    http<{ source: string; agents: OmnigentAgentDef[]; error: string | null }>('/omnigent/agents'),
  omnigentHosts: () =>
    http<{ source: string; hosts: OmnigentHostDef[]; error: string | null }>('/omnigent/hosts'),
  omnigentScheduledTasks: () =>
    http<{ source: string; scheduled_tasks: OmnigentScheduledTask[]; error: string | null }>('/omnigent/scheduled-tasks'),
  omnigentCreateScheduledTask: (payload: {
    name: string
    agent_id: string
    prompt: string
    cron_expression: string
    workspace?: string
    host_id?: string
    model?: string
  }) =>
    http<{ source: string; scheduled_task: OmnigentScheduledTask | null; error: string | null }>(
      '/omnigent/scheduled-tasks',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  omnigentRunScheduledTask: (taskId: string) =>
    http<{ source: string; result: unknown; error: string | null }>(
      `/omnigent/scheduled-tasks/${encodeURIComponent(taskId)}/run`,
      { method: 'POST' },
    ),
  omnigentDeleteScheduledTask: (taskId: string) =>
    http<{ source: string; success: boolean; error: string | null }>(
      `/omnigent/scheduled-tasks/${encodeURIComponent(taskId)}`,
      { method: 'DELETE' },
    ),
}

export function readOmnigentStream(
  sessionId: string,
  onEvent: (event: { type?: string; event_type?: string; data?: unknown; [key: string]: unknown }) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${BASE}/omnigent/sessions/${encodeURIComponent(sessionId)}/stream`)
  es.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data)
      onEvent(data)
    } catch {
      /* ignore non-json */
    }
  }
  es.onerror = (e) => {
    if (onError) onError(e)
  }
  return es
}

export async function readStream(onEvent: (event: { type: string; task?: Task }) => void): Promise<EventSource> {
  const es = new EventSource(BASE + '/stream')
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as { type: string; task?: Task })
    } catch {
      /* ignore */
    }
  }
  es.onerror = () => es.close()
  return es
}

// ── Omnigent session browsing & client models ──

export type OmnigentSessionStatus = 'idle' | 'running' | 'waiting' | 'failed'

export interface OmnigentBlock {
  type: string
  text?: string
  [key: string]: unknown
}

export interface OmnigentItem {
  id: string
  type: string
  status?: string
  response_id?: string
  created_at?: number
  role?: 'user' | 'assistant'
  content?: string | OmnigentBlock[]
  model?: string
  name?: string
  arguments?: string
  call_id?: string
  output?: string
  message?: string
  code?: string
  source?: string
  summary?: OmnigentBlock[]
  event_type?: string
  resource_type?: string
  data?: Record<string, unknown>
  [key: string]: unknown
}

export interface OmnigentElicitation {
  id: string
  type?: string
  message?: string
  prompt?: string
  schema?: Record<string, unknown>
  options?: string[]
  [key: string]: unknown
}

export interface OmnigentSkill {
  name: string
  description?: string
  [key: string]: unknown
}

export interface OmnigentTodo {
  id?: string
  content?: string
  text?: string
  status?: 'completed' | 'in_progress' | 'pending' | string
  [key: string]: unknown
}

export interface OmnigentSession {
  id: string
  agent_id: string
  agent_name: string | null
  status: OmnigentSessionStatus
  title: string | null
  created_at: number
  updated_at: number
  archived: boolean
  host_id: string | null
  runner_online: boolean | null
  host_online: boolean | null
  workspace: string | null
  git_branch: string | null
  harness?: string | null
  pending_elicitations_count?: number
  pending_elicitations?: OmnigentElicitation[]
  skills?: OmnigentSkill[]
  todos?: OmnigentTodo[]
  owner?: string | null
  items?: OmnigentItem[]
  labels?: Record<string, unknown>
  total_cost_usd?: number | null
  last_task_error?: { message?: string; code?: string; [key: string]: unknown } | null
  [key: string]: unknown
}

export interface OmnigentEnvironment {
  id: string
  object?: string
  type?: string
  name?: string
  metadata?: {
    root?: string
    environment_type?: string
    terminal_name?: string
    session_key?: string
    [key: string]: unknown
  }
  [key: string]: unknown
}

export interface OmnigentFilesystemEntry {
  id?: string
  name: string
  path: string
  type: 'file' | 'directory'
  bytes?: number | null
  modified_at?: number | null
}

export interface OmnigentFilesystemResponse {
  object?: string
  base?: string
  path?: string
  content?: string
  content_type?: string
  data?: OmnigentFilesystemEntry[]
  truncated?: boolean
}

export interface OmnigentChangeEntry {
  path: string
  name?: string
  status: 'created' | 'modified' | 'deleted' | string
  bytes?: number
  lines_added?: number | null
  lines_removed?: number | null
  modified_at?: number
}

export interface OmnigentTerminal {
  id: string
  name?: string
  metadata?: {
    running?: boolean
    terminal_name?: string
    session_key?: string
    tmux_target?: string
    direct_attach_url?: string
    [key: string]: unknown
  }
}

export interface OmnigentAgentDef {
  id: string
  name: string
  description?: string | null
  harness: string
  builtin: boolean
  version?: number
  mcp_servers?: unknown[]
  skills?: OmnigentSkill[]
  policies?: unknown[]
  created_at?: number
  [key: string]: unknown
}

export interface OmnigentHostDef {
  host_id: string
  name: string
  status: string
  owner?: string
  configured_harnesses?: Record<string, boolean | string>
  [key: string]: unknown
}

export interface OmnigentScheduledTask {
  id: string
  name: string
  agent_id: string
  agent_name?: string
  prompt: string
  cron_expression: string
  status?: string
  last_run_at?: number
  next_run_at?: number
  workspace?: string
  host_id?: string
  [key: string]: unknown
}

export interface OmnigentListResponse {
  source: string
  sessions: OmnigentSession[]
  has_more: boolean
  error: string | null
  base_url?: string
}

export interface OmnigentSessionResponse {
  source: string
  session: OmnigentSession | null
  error: string | null
  base_url?: string
}

export interface OmnigentItemsResponse {
  source: string
  items: OmnigentItem[]
  error: string | null
  base_url?: string
}

export const STATUS_META: Record<
  Status,
  { label: string; color: string; badgeClass: string }
> = {
  backlog: {
    label: 'Backlog',
    color: '#94a3b8',
    badgeClass: 'border-slate-500/40 text-slate-300 bg-slate-500/10',
  },
  queued: {
    label: 'Queued',
    color: '#38bdf8',
    badgeClass: 'border-sky-500/40 text-sky-400 bg-sky-500/10',
  },
  host_provisioning: {
    label: 'Provisioning Host',
    color: '#fbbf24',
    badgeClass: 'border-amber-500/40 text-amber-400 bg-amber-500/10',
  },
  executing: {
    label: 'Executing',
    color: '#60a5fa',
    badgeClass: 'border-blue-500/40 text-blue-400 bg-blue-500/10',
  },
  verifying: {
    label: 'Verifying',
    color: '#c084fc',
    badgeClass: 'border-purple-500/40 text-purple-400 bg-purple-500/10',
  },
  needs_review: {
    label: 'Needs Review',
    color: '#fbbf24',
    badgeClass: 'border-amber-500/40 text-amber-400 bg-amber-500/10',
  },
  done: {
    label: 'Done',
    color: '#34d399',
    badgeClass: 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10',
  },
  rejected: {
    label: 'Rejected',
    color: '#f87171',
    badgeClass: 'border-red-500/40 text-red-400 bg-red-500/10',
  },
  blocked: {
    label: 'Blocked',
    color: '#f87171',
    badgeClass: 'border-red-500/40 text-red-400 bg-red-500/10',
  },
}

export const BOARD_COLUMNS: Status[] = [
  'backlog',
  'queued',
  'host_provisioning',
  'executing',
  'verifying',
  'needs_review',
  'done',
  'rejected',
  'blocked',
]

export const PLAN_STATUS_META: Record<
  PlanStatus,
  { label: string; color: string; badgeClass: string }
> = {
  none: {
    label: 'no plan',
    color: '#94a3b8',
    badgeClass: 'border-slate-500/40 text-slate-300 bg-slate-500/10',
  },
  planning: {
    label: 'planning',
    color: '#60a5fa',
    badgeClass: 'border-blue-500/40 text-blue-400 bg-blue-500/10',
  },
  awaiting_approval: {
    label: 'plan awaiting approval',
    color: '#fbbf24',
    badgeClass: 'border-amber-500/40 text-amber-400 bg-amber-500/10',
  },
  approved: {
    label: 'plan approved',
    color: '#34d399',
    badgeClass: 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10',
  },
  implementing: {
    label: 'implementing',
    color: '#c084fc',
    badgeClass: 'border-purple-500/40 text-purple-400 bg-purple-500/10',
  },
  done: {
    label: 'plan done',
    color: '#34d399',
    badgeClass: 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10',
  },
  failed: {
    label: 'plan failed',
    color: '#f87171',
    badgeClass: 'border-red-500/40 text-red-400 bg-red-500/10',
  },
}

export function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return ''
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}