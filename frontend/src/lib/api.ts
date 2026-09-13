export type Status =
  | 'backlog'
  | 'queued'
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
  workspace: string | null
  current_attempt: number
  max_attempts: number
  escalation_reason: string | null
  plan_required: boolean
  plan_status: PlanStatus
  plan_text: string | null
  pr_url: string | null
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
}

export interface TaskCreateInput {
  title: string
  intent?: string
  priority: Priority
  risk_tier: RiskTier
  agent_capability: string
  max_attempts?: number
  plan_required?: boolean
  workspace?: string
  context?: { type: string; ref: string; description?: string }[]
  criteria: { description: string; check_type: CheckType; check_config: Record<string, unknown> }[]
  depends_on?: string[]
}

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
  approveExecution: (id: string, note: string) =>
    http<Task>(`/tasks/${id}/approve_execution`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  reviews: () => http<Task[]>('/reviews'),
  metrics: () => http<Metrics>('/metrics'),
  capabilities: () =>
    http<{ name: string; adapter: string }[]>('/capabilities'),
  parse: (text: string) =>
    http<{ parsed: Partial<TaskCreateInput>; confidence: number; note: string }>('/parse', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  seed: () => http<{ created: number }>('/demo/seed', { method: 'POST' }),
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

export const STATUS_META: Record<Status, { label: string; color: string }> = {
  backlog: { label: 'Backlog', color: '#8e8e93' },
  queued: { label: 'Queued', color: '#5e9ce6' },
  executing: { label: 'Executing', color: '#0a84ff' },
  verifying: { label: 'Verifying', color: '#bf5af2' },
  needs_review: { label: 'Needs Review', color: '#ff9f0a' },
  done: { label: 'Done', color: '#30d158' },
  rejected: { label: 'Rejected', color: '#ff453a' },
  blocked: { label: 'Blocked', color: '#ffd60a' },
}

export const BOARD_COLUMNS: Status[] = [
  'backlog',
  'queued',
  'executing',
  'verifying',
  'needs_review',
  'done',
  'rejected',
  'blocked',
]

export const PLAN_STATUS_META: Record<PlanStatus, { label: string; color: string }> = {
  none: { label: 'no plan', color: '#8e8e93' },
  planning: { label: 'planning', color: '#0a84ff' },
  awaiting_approval: { label: 'plan awaiting approval', color: '#ff9f0a' },
  approved: { label: 'plan approved', color: '#30d158' },
  implementing: { label: 'implementing', color: '#bf5af2' },
  done: { label: 'plan done', color: '#30d158' },
  failed: { label: 'plan failed', color: '#ff453a' },
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