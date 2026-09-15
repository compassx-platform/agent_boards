import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Columns3,
  PlusCircle,
  ClipboardCheck,
  Bot,
  Settings as SettingsIcon,
  Sun,
  Moon,
  Clock,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Check,
  X,
  ExternalLink,
  Terminal,
  Cpu,
  RotateCw,
  Sparkles,
  GitBranch,
  Folder,
  FileText,
  Shield,
  ListChecks,
  Trash2,
  Play,
  TrendingUp,
  Activity,
  History,
  ChevronDown,
  Layers,
  Search,
  MessageSquare,
} from 'lucide-react'
import type {
  Task,
  TaskCreateInput,
  Metrics,
  Criterion,
  Priority,
  RiskTier,
  HarnessesResponse,
  CompassXApp,
  CompassXWorkspace,
  SettingsResponse,
} from './lib/api'
import {
  BOARD_COLUMNS,
  DEFAULT_HARNESS,
  PLAN_STATUS_META,
  PROVISION_STEP_LABELS,
  STATUS_META,
  readStream,
  timeAgo,
  api,
} from './lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Checkout from './components/Checkout'
import SessionsPage from './Sessions'
import { cn } from '@/lib/utils'

// ------------------------------------------------------------------------- data hook
function useTaskStore() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [caps, setCaps] = useState<{ name: string; adapter: string }[]>([])
  const [harnessData, setHarnessData] = useState<HarnessesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [t, m, c, h] = await Promise.all([
        api.listTasks(),
        api.metrics(),
        api.capabilities(),
        api.harnesses(),
      ])
      setTasks(t)
      setMetrics(m)
      setCaps(c)
      setHarnessData(h)
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    refresh()
    const esPromise = readStream(() => {
      refresh()
    })
    const poll = setInterval(refresh, 5000)
    return () => {
      clearInterval(poll)
      esPromise.then((es) => es.close())
    }
  }, [refresh])

  return { tasks, metrics, caps, harnessData, error, refresh }
}

// -------------------------------------------------------------------- priority & risk styling
function PriorityBadge({ priority }: { priority: string }) {
  const variants: Record<string, string> = {
    urgent: 'border-amber-500/40 text-amber-400 bg-amber-500/10',
    high: 'border-orange-500/40 text-orange-400 bg-orange-500/10',
    normal: 'border-blue-500/40 text-blue-400 bg-blue-500/10',
    low: 'border-cyan-500/30 text-cyan-400 bg-cyan-500/10',
  }
  return (
    <Badge
      variant="outline"
      className={cn('text-[11px] font-mono capitalize px-1.5 py-0 h-4.5', variants[priority] || '')}
    >
      {priority}
    </Badge>
  )
}

function RiskBadge({ risk }: { risk: string }) {
  const variants: Record<string, string> = {
    high: 'border-red-500/40 text-red-400 bg-red-500/10',
    medium: 'border-amber-500/40 text-amber-400 bg-amber-500/10',
    low: 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10',
  }
  return (
    <Badge
      variant="outline"
      className={cn('text-[11px] font-mono capitalize px-1.5 py-0 h-4.5', variants[risk] || '')}
    >
      {risk} risk
    </Badge>
  )
}

function StatusDot({ status }: { status: string }) {
  const meta = STATUS_META[status] || { color: '#94a3b8', label: status }
  return (
    <span
      className="size-2 rounded-full inline-block shrink-0 shadow-xs"
      style={{ backgroundColor: meta.color }}
    />
  )
}

// -------------------------------------------------------------------- Task Card
function TaskCard({ task, onClick }: { task: Task; onClick: (id: string) => void }) {
  const meta = STATUS_META[task.status]
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onClick(task.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(task.id)
        }
      }}
      className="group relative flex flex-col gap-2.5 p-3.5 bg-card/80 hover:bg-card border border-border/60 hover:border-border-strong rounded-xl shadow-2xs hover:shadow-xs transition-all cursor-pointer text-left select-none"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-[13.5px] leading-snug text-foreground group-hover:text-primary transition-colors line-clamp-2">
          {task.title}
        </span>
        <span
          className="text-[11px] font-semibold font-mono shrink-0 px-1.5 py-0.5 rounded-md border"
          style={{
            borderColor: `${meta.color}40`,
            backgroundColor: `${meta.color}15`,
            color: meta.color,
          }}
        >
          {meta.label}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <PriorityBadge priority={task.priority} />
        <RiskBadge risk={task.risk_tier} />
        <Badge
          variant="secondary"
          className="text-[11px] font-mono px-1.5 py-0 h-4.5 bg-muted/80 text-foreground/90 border border-border/70 flex items-center gap-1 font-medium"
          title="harness"
        >
          <Cpu className="size-2.5 text-sky-500 dark:text-sky-400" />
          <span>{task.harness || DEFAULT_HARNESS}</span>
        </Badge>
        {task.compassx_app_name && (
          <Badge
            variant="outline"
            className="text-[11px] font-mono px-1.5 py-0 h-4.5 border-emerald-500/30 text-emerald-400 bg-emerald-500/10 flex items-center gap-1 font-medium"
          >
            <Cpu className="size-2.5" />
            {task.compassx_app_name}
          </Badge>
        )}
        {task.session_id && (
          <Badge
            variant="outline"
            className="text-[11px] font-mono px-1.5 py-0 h-4.5 border-sky-500/40 text-sky-600 dark:text-sky-300 bg-sky-500/10 flex items-center gap-1 font-medium"
          >
            <Sparkles className="size-2.5" />
            {task.session_id.slice(0, 8)}
          </Badge>
        )}
        {task.escalation_reason && (
          <Badge
            variant="destructive"
            className="text-[11px] font-mono px-1.5 py-0 h-4.5 flex items-center gap-1"
          >
            <AlertTriangle className="size-2.5" />
            escalated
          </Badge>
        )}
      </div>

      <div className="flex items-center justify-between text-[11.5px] text-muted-foreground pt-1 border-t border-border/30">
        <span className="truncate max-w-[140px] font-mono">{task.agent_capability}</span>
        <span className="flex items-center gap-1 shrink-0">
          <Clock className="size-3" />
          {timeAgo(task.updated_at)}
        </span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------------ Board
function Board({ tasks, onClick }: { tasks: Task[]; onClick: (id: string) => void }) {
  const byStatus = useMemo(() => {
    const map: Record<string, Task[]> = {
      backlog: [],
      queued: [],
      host_provisioning: [],
      executing: [],
      verifying: [],
      needs_review: [],
      done: [],
      rejected: [],
      blocked: [],
    }
    for (const t of tasks) if (map[t.status]) map[t.status].push(t)
    return map
  }, [tasks])

  return (
    <div className="flex-1 flex gap-3.5 p-4.5 overflow-x-auto min-h-0 bg-background/40">
      {BOARD_COLUMNS.map((status) => {
        const columnTasks = byStatus[status] || []
        const meta = STATUS_META[status]
        return (
          <div
            key={status}
            className="w-72 shrink-0 bg-card/60 backdrop-blur-xs border border-border/60 rounded-xl flex flex-col max-h-full overflow-hidden shadow-2xs"
          >
            <div className="p-3 border-b border-border/40 flex items-center justify-between font-medium text-xs tracking-wide uppercase text-muted-foreground bg-muted/20">
              <div className="flex items-center gap-2">
                <StatusDot status={status} />
                <span className="text-foreground/90 font-semibold">{meta.label}</span>
              </div>
              <Badge
                variant="secondary"
                className="text-[11px] font-mono px-1.5 py-0 h-5 rounded-full bg-muted/80 text-muted-foreground"
              >
                {columnTasks.length}
              </Badge>
            </div>
            <div className="p-2.5 overflow-y-auto flex-1 flex flex-col gap-2.5">
              {columnTasks.map((t) => (
                <TaskCard key={t.id} task={t} onClick={onClick} />
              ))}
              {columnTasks.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10 text-muted-foreground/60 text-xs">
                  <span>No tasks</span>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------- new task form
const CHECK_LABEL: Record<string, string> = {
  automated_test: 'Automated test (shell command)',
  schema_check: 'Schema check',
  output_match: 'Output match (regex)',
  human_approval: 'Human approval',
  manual_checklist: 'Manual checklist',
}

const CHECK_HINT: Record<string, string> = {
  automated_test: '{"command": "grep -q success artifact.txt"}',
  schema_check: '{"required_keys": ["status"]}',
  output_match: '{"pattern": "success"}',
  human_approval: '{}',
  manual_checklist: '{}',
}

interface CriterionDraft {
  description: string
  check_type: string
  check_config: string
}

interface ContextDraft {
  type: string
  ref: string
  description: string
}

function NewTaskForm({
  tasks,
  caps,
  harnessData,
  refresh,
  onCreated,
}: {
  tasks: Task[]
  caps: { name: string; adapter: string }[]
  harnessData: HarnessesResponse | null
  refresh: () => Promise<void>
  onCreated: (id: string) => void
}) {
  const [title, setTitle] = useState('')
  const [intent, setIntent] = useState('')
  const [priority, setPriority] = useState<Priority>('normal')
  const [risk, setRisk] = useState<RiskTier>('low')
  const [capability, setCapability] = useState('default')
  const [harness, setHarness] = useState(harnessData?.default ?? DEFAULT_HARNESS)
  const [planRequired, setPlanRequired] = useState(false)
  const [bypassVerification, setBypassVerification] = useState(true)
  const [bypassOutcome, setBypassOutcome] = useState('needs_review')
  const [workspace, setWorkspace] = useState('')
  const [deps, setDeps] = useState<string[]>([])
  const [criteria, setCriteria] = useState<CriterionDraft[]>([
    {
      description: 'Agent output indicates success',
      check_type: 'output_match',
      check_config: '{"pattern": "success"}',
    },
  ])
  const [context, setContext] = useState<ContextDraft[]>([])
  const [conversation, setConversation] = useState('')
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [apps, setApps] = useState<CompassXApp[]>([])
  const [appsError, setAppsError] = useState<string | null>(null)
  const [appId, setAppId] = useState('')
  const [reuseWorkspace, setReuseWorkspace] = useState(false)
  const [appWorkspaces, setAppWorkspaces] = useState<CompassXWorkspace[]>([])
  const [appWsId, setAppWsId] = useState('')

  const loadApps = useCallback(async () => {
    try {
      const res = await api.compassxApps()
      setApps(res.apps ?? [])
      setAppsError(res.error ? String(res.error).slice(0, 120) : null)
    } catch (e) {
      setAppsError(String(e))
    }
  }, [])

  useEffect(() => {
    loadApps()
  }, [loadApps])

  useEffect(() => {
    setAppWsId('')
    setAppWorkspaces([])
    if (appId && reuseWorkspace) {
      api
        .compassxWorkspaces(appId)
        .then((res) => setAppWorkspaces(res.workspaces ?? []))
        .catch((e) => setAppsError(String(e)))
    }
  }, [appId, reuseWorkspace])

  function applyParsed(p: Partial<TaskCreateInput>) {
    setTitle(p.title ?? '')
    setIntent(p.intent ?? '')
    if (p.priority) setPriority(p.priority)
    if (p.risk_tier) setRisk(p.risk_tier)
    if (p.agent_capability) setCapability(p.agent_capability)
    if (p.harness) setHarness(p.harness)
    if (p.plan_required !== undefined) setPlanRequired(p.plan_required)
    if (p.bypass_verification !== undefined) setBypassVerification(p.bypass_verification)
    if (p.verification_bypass_outcome) setBypassOutcome(p.verification_bypass_outcome)
    if (p.workspace) setWorkspace(p.workspace)
    if (p.compassx_app_id) setAppId(p.compassx_app_id)
    if (p.criteria && p.criteria.length) {
      setCriteria(
        p.criteria.map((c) => ({
          description: c.description,
          check_type: c.check_type,
          check_config: JSON.stringify(c.check_config),
        })),
      )
    }
  }

  async function parseIt() {
    if (!conversation.trim()) return
    setParsing(true)
    setError(null)
    try {
      const res = await api.parse(conversation.trim())
      applyParsed(res.parsed)
    } catch (e) {
      setError(String(e))
    } finally {
      setParsing(false)
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const payload: TaskCreateInput = {
        title: title.trim(),
        intent: intent.trim(),
        priority,
        risk_tier: risk,
        agent_capability: capability,
        harness,
        plan_required: planRequired,
        bypass_verification: bypassVerification,
        verification_bypass_outcome: bypassOutcome,
        workspace: workspace.trim() || undefined,
        compassx_app_id: appId || undefined,
        compassx_app_name: appId ? apps.find((a) => a.id === appId)?.name : undefined,
        compassx_workspace_id: appId && reuseWorkspace && appWsId ? appWsId : undefined,
        depends_on: deps,
        context: context.filter((c) => c.ref.trim()),
        criteria: criteria
          .filter((c) => c.description.trim())
          .map((c) => {
            let cfg = {}
            try {
              cfg = c.check_config.trim() ? JSON.parse(c.check_config) : {}
            } catch {
              cfg = { _malformed: c.check_config }
            }
            return {
              description: c.description.trim(),
              check_type: c.check_type as Criterion['check_type'],
              check_config: cfg,
            }
          }),
      }
      if (!payload.title) throw new Error('title is required')
      if (!payload.criteria.length)
        throw new Error('at least one definition-of-done criterion is required')
      const task = await api.createTask(payload)
      await refresh()
      onCreated(task.id)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-foreground">New Task</h2>
        <p className="text-sm text-muted-foreground mt-0.5">
          Create an autonomous agent assignment with clear intent and definition of done.
        </p>
      </div>

      {/* AI Conversational Parsing Card */}
      <div className="bg-card/70 border border-border/70 rounded-xl p-5 shadow-xs flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-sky-500 dark:text-sky-400" />
          <h3 className="text-sm font-semibold text-foreground">Conversational Task Creation</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          Describe what you want the agent to do in plain natural language, and let AI structure the
          task fields for you.
        </p>
        <div className="flex gap-2 mt-1">
          <input
            value={conversation}
            onChange={(e) => setConversation(e.target.value)}
            placeholder='e.g. "URGENT: Fix the auth redirect loop in production and add unit tests"'
            className="flex-1 bg-background border border-input rounded-lg px-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <Button
            type="button"
            onClick={parseIt}
            disabled={parsing || !conversation.trim()}
            variant="secondary"
            size="default"
            className="shrink-0"
          >
            {parsing ? <RotateCw className="size-3.5 animate-spin mr-1.5" /> : null}
            {parsing ? 'Parsing…' : 'Parse Prompt'}
          </Button>
        </div>
      </div>

      {/* Main Task Form */}
      <form onSubmit={submit} className="bg-card border border-border/70 rounded-xl p-6 shadow-xs flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Task Title *
          </label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Short, action-oriented title"
            className="bg-background border border-input rounded-lg px-3.5 py-2 text-sm font-medium text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Task Intent / Outcome
          </label>
          <textarea
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            rows={3}
            placeholder="Plain-language description of desired outcome and context"
            className="bg-background border border-input rounded-lg p-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-accent resize-y"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Priority
            </label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              className="bg-background border border-input rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Risk Tier
            </label>
            <select
              value={risk}
              onChange={(e) => setRisk(e.target.value as RiskTier)}
              className="bg-background border border-input rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="low">Low (auto-approve)</option>
              <option value="medium">Medium (auto-approve)</option>
              <option value="high">High (requires sign-off)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Agent Capability
            </label>
            <select
              value={capability}
              onChange={(e) => setCapability(e.target.value)}
              className="bg-background border border-input rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {caps.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Engine / Harness
            </label>
            <select
              value={harness}
              onChange={(e) => setHarness(e.target.value)}
              className="bg-background border border-input rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {(harnessData?.harnesses ?? []).map((h) => (
                <option key={h.name} value={h.name}>
                  {h.name}
                  {h.name === harnessData?.default ? ' (default)' : ''}
                </option>
              ))}
              {!harnessData && <option value={harness}>{harness}</option>}
            </select>
          </div>
        </div>

        {/* CompassX Dev Environment */}
        <div className="flex flex-col gap-2 p-4 bg-muted/20 border border-border/50 rounded-lg">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <Cpu className="size-3.5 text-sky-500 dark:text-sky-400" />
            CompassX Target Application
          </label>
          <select
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
            className="bg-background border border-input rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">— None (run on local default host) —</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} {a.git_branch ? `(${a.git_branch})` : ''}
              </option>
            ))}
          </select>
          {appsError && <p className="text-xs text-destructive">{appsError}</p>}
          {appId !== '' && (
            <div className="flex flex-col gap-2 mt-2 pt-2 border-t border-border/40">
              <label className="flex items-center gap-2 text-xs font-medium text-foreground cursor-pointer">
                <input
                  type="checkbox"
                  checked={reuseWorkspace}
                  onChange={(e) => setReuseWorkspace(e.target.checked)}
                  className="rounded border-input text-primary focus:ring-primary"
                />
                Reuse an existing dev workspace (redo task)
              </label>
              {reuseWorkspace && (
                <select
                  value={appWsId}
                  onChange={(e) => setAppWsId(e.target.value)}
                  className="bg-background border border-input rounded-lg px-3 py-1.5 text-sm text-foreground"
                >
                  <option value="">— Create fresh workspace —</option>
                  {appWorkspaces.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name || w.id} ({w.folder_path})
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        {/* Plan & Verification Toggles */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex items-start gap-2.5 p-3.5 bg-muted/20 border border-border/50 rounded-lg cursor-pointer">
            <input
              type="checkbox"
              checked={planRequired}
              onChange={(e) => setPlanRequired(e.target.checked)}
              className="mt-0.5 rounded border-input text-primary focus:ring-primary"
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium text-foreground">Require Implementation Plan</span>
              <span className="text-xs text-muted-foreground">
                Agent plans first → human approves → agent implements &amp; opens PR
              </span>
            </div>
          </label>

          <label className="flex items-start gap-2.5 p-3.5 bg-muted/20 border border-border/50 rounded-lg cursor-pointer">
            <input
              type="checkbox"
              checked={bypassVerification}
              onChange={(e) => setBypassVerification(e.target.checked)}
              className="mt-0.5 rounded border-input text-primary focus:ring-primary"
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium text-foreground">Bypass Verification</span>
              <span className="text-xs text-muted-foreground">
                Skip automated tests and route finished task straight to review
              </span>
            </div>
          </label>
        </div>

        {/* Definition of Done Criteria */}
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <ListChecks className="size-3.5 text-sky-500 dark:text-sky-400" />
              Definition of Done (Criteria) *
            </label>
            <Button
              type="button"
              variant="outline"
              size="xs"
              onClick={() =>
                setCriteria([
                  ...criteria,
                  {
                    description: '',
                    check_type: 'output_match',
                    check_config: '{"pattern": "success"}',
                  },
                ])
              }
              className="h-6 text-xs gap-1"
            >
              <PlusCircle className="size-3" /> Add Criterion
            </Button>
          </div>

          <div className="flex flex-col gap-2">
            {criteria.map((c, i) => (
              <div
                key={i}
                className="flex items-center gap-2 p-2.5 bg-muted/30 border border-border/50 rounded-lg"
              >
                <input
                  value={c.description}
                  onChange={(e) =>
                    setCriteria(
                      criteria.map((x, j) =>
                        j === i ? { ...x, description: e.target.value } : x,
                      ),
                    )
                  }
                  placeholder="Criterion description (e.g. Test suite passes)"
                  className="flex-2 bg-background border border-input rounded-md px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-accent"
                />
                <select
                  value={c.check_type}
                  onChange={(e) =>
                    setCriteria(
                      criteria.map((x, j) =>
                        j === i ? { ...x, check_type: e.target.value } : x,
                      ),
                    )
                  }
                  className="bg-background border border-input rounded-md px-2.5 py-1.5 text-xs text-foreground shrink-0"
                >
                  {Object.entries(CHECK_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                {c.check_type !== 'human_approval' && c.check_type !== 'manual_checklist' && (
                  <input
                    value={c.check_config}
                    onChange={(e) =>
                      setCriteria(
                        criteria.map((x, j) =>
                          j === i ? { ...x, check_config: e.target.value } : x,
                        ),
                      )
                    }
                    placeholder={CHECK_HINT[c.check_type]}
                    className="flex-1 bg-background border border-input rounded-md px-3 py-1.5 text-xs font-mono text-foreground"
                  />
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => setCriteria(criteria.filter((_, j) => j !== i))}
                  className="text-muted-foreground hover:text-destructive shrink-0"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 p-3 text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-lg">
            <AlertCircle className="size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-3 border-t border-border/50">
          <Button type="submit" disabled={saving} size="default" className="gap-2">
            {saving ? <RotateCw className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
            {saving ? 'Creating Task…' : 'Create & Queue Task'}
          </Button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------- Reviews
function Reviews({
  refresh,
  onOpen,
}: {
  refresh: () => Promise<void>
  onOpen: (id: string) => void
}) {
  const [items, setItems] = useState<Task[]>([])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    void api.reviews().then((r) => alive && setItems(r)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  async function act(id: string, action: 'approve' | 'retry' | 'reject' | 'approve_plan') {
    setBusy(id)
    setError(null)
    try {
      await api.review(id, action, notes[id] ?? '')
      setItems(items.filter((t) => t.id !== id))
      await refresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full flex flex-col gap-5">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-foreground">Review Queue</h2>
        <p className="text-sm text-muted-foreground mt-0.5">
          Tasks awaiting human inspection, plan sign-off, or verification feedback.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-lg">
          <AlertCircle className="size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {items.length === 0 ? (
        <div className="bg-card border border-border/60 rounded-xl p-12 text-center flex flex-col items-center justify-center gap-2">
          <CheckCircle2 className="size-8 text-emerald-400/80" />
          <p className="text-sm font-medium text-foreground">No tasks awaiting review</p>
          <p className="text-xs text-muted-foreground">All queued agent tasks are progressing smoothly.</p>
        </div>
      ) : (
        items.map((t) => (
          <div
            key={t.id}
            className="bg-card border border-border/70 rounded-xl p-5 shadow-xs flex flex-col gap-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-1.5">
                <button
                  type="button"
                  onClick={() => onOpen(t.id)}
                  className="text-left font-semibold text-base text-foreground hover:text-primary transition-colors"
                >
                  {t.title}
                </button>
                <div className="flex flex-wrap items-center gap-2">
                  <RiskBadge risk={t.risk_tier} />
                  {t.plan_required && (
                    <Badge variant="outline" className="border-amber-500/40 text-amber-400 text-xs">
                      plan-first
                    </Badge>
                  )}
                  <Badge variant="secondary" className="font-mono text-xs">
                    Attempt {t.current_attempt}/{t.max_attempts}
                  </Badge>
                </div>
              </div>
            </div>

            {t.escalation_reason && (
              <div className="flex items-center gap-2 p-2.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs rounded-lg">
                <AlertTriangle className="size-4 shrink-0" />
                <span>{t.escalation_reason}</span>
              </div>
            )}

            {t.plan_status === 'awaiting_approval' ? (
              <div className="flex flex-col gap-2 p-3.5 bg-muted/40 border border-border/50 rounded-lg">
                <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
                  Proposed Implementation Plan
                </h4>
                <pre className="text-xs font-mono bg-background p-3 rounded-md overflow-x-auto max-h-60 text-muted-foreground whitespace-pre-wrap">
                  {t.plan_text ?? '(Plan generated, click task to inspect details)'}
                </pre>
              </div>
            ) : (
              <div className="flex flex-col gap-1.5 p-3 bg-muted/30 border border-border/40 rounded-lg">
                {t.criteria.map((c) => (
                  <div key={c.id} className="flex items-center gap-2 text-xs">
                    <span
                      className={cn(
                        'font-bold font-mono',
                        c.result === 'pass'
                          ? 'text-emerald-400'
                          : c.result === 'fail'
                            ? 'text-red-400'
                            : 'text-amber-400',
                      )}
                    >
                      {c.result ?? 'pending'}
                    </span>
                    <span className="text-foreground">{c.description}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-col sm:flex-row items-center gap-2 pt-2 border-t border-border/40">
              <input
                value={notes[t.id] ?? ''}
                onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })}
                placeholder={
                  t.plan_status === 'awaiting_approval'
                    ? 'Feedback or instructions to agent (optional)'
                    : 'Reviewer comment or instructions'
                }
                className="flex-1 w-full bg-background border border-input rounded-lg px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-accent"
              />
              <div className="flex items-center gap-2 shrink-0">
                {t.plan_status === 'awaiting_approval' ? (
                  <>
                    <Button
                      size="sm"
                      onClick={() => act(t.id, 'approve_plan')}
                      disabled={busy === t.id}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5"
                    >
                      <Check className="size-3.5" /> Approve Plan → Implement
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => act(t.id, 'retry')}
                      disabled={busy === t.id}
                      className="gap-1.5"
                    >
                      <RotateCw className="size-3.5" /> Re-plan
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => act(t.id, 'reject')}
                      disabled={busy === t.id}
                    >
                      Reject
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      size="sm"
                      onClick={() => act(t.id, 'approve')}
                      disabled={busy === t.id}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5"
                    >
                      <Check className="size-3.5" /> Approve
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => act(t.id, 'retry')}
                      disabled={busy === t.id}
                      className="gap-1.5"
                    >
                      <RotateCw className="size-3.5" /> Retry with Note
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => act(t.id, 'reject')}
                      disabled={busy === t.id}
                    >
                      Reject
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Settings
function Settings() {
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const reload = useCallback(async () => {
    const next = await api.settings()
    setData(next)
    setDraft(
      Object.fromEntries(
        Object.entries(next.settings).map(([k, v]) => [k, String(v)]),
      ),
    )
    setSaved(false)
  }, [])

  useEffect(() => {
    void reload().catch(() => setError('failed to load settings'))
  }, [reload])

  useEffect(() => {
    setSaved(false)
  }, [draft])

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-muted-foreground text-sm">
        <RotateCw className="size-4 animate-spin mr-2" /> Loading settings…
      </div>
    )
  }

  const entries = Object.entries(data.definitions)

  const save = async () => {
    const updates: Record<string, unknown> = {}
    let firstError: string | null = null
    for (const [key, def] of entries) {
      const raw = draft[key] ?? ''
      if (def.type === 'number') {
        const n = Number(raw)
        if (Number.isNaN(n)) {
          firstError = firstError ?? `${def.label} must be a number`
          continue
        }
        updates[key] = n
      } else {
        updates[key] = raw
      }
    }
    if (firstError) {
      setError(firstError)
      return
    }
    setError(null)
    try {
      const next = await api.updateSettings(updates)
      setData(next)
      setDraft(Object.fromEntries(Object.entries(next.settings).map(([k, v]) => [k, String(v)])))
      setSaved(true)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-foreground">Board Settings</h2>
        <p className="text-sm text-muted-foreground mt-0.5">
          Configure agent limits, verification policies, and execution thresholds.
        </p>
      </div>

      <div className="bg-card border border-border/70 rounded-xl divide-y divide-border/40 shadow-xs overflow-hidden">
        {entries.length === 0 && (
          <p className="p-6 text-center text-sm text-muted-foreground">No managed settings yet</p>
        )}
        {entries.map(([key, def]) => {
          const current = String(data.settings[key] ?? '')
          const dirty = (draft[key] ?? '') !== current
          return (
            <div key={key} className="p-4 flex items-center justify-between gap-6">
              <div className="flex flex-col gap-0.5 max-w-md">
                <span className="text-sm font-semibold text-foreground">{def.label}</span>
                {def.description && (
                  <span className="text-xs text-muted-foreground">{def.description}</span>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {def.type === 'number' ? (
                  <input
                    type="number"
                    value={draft[key] ?? ''}
                    min={def.min}
                    max={def.max}
                    step={def.step}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    className="bg-background border border-input rounded-md px-3 py-1.5 text-xs text-foreground font-mono w-28 text-right focus:ring-1 focus:ring-accent"
                  />
                ) : (
                  <input
                    value={draft[key] ?? ''}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    className="bg-background border border-input rounded-md px-3 py-1.5 text-xs text-foreground w-48 focus:ring-1 focus:ring-accent"
                  />
                )}
                {dirty && (
                  <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-500/30">
                    unsaved
                  </Badge>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-lg">
          <AlertCircle className="size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="flex justify-end gap-3">
        <Button variant="ghost" size="sm" onClick={() => reload()}>
          Reset
        </Button>
        <Button size="sm" onClick={() => void save()} className="gap-1.5">
          {saved ? <Check className="size-3.5" /> : null}
          {saved ? 'Saved ✓' : 'Save Changes'}
        </Button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Task Detail Drawer
function AuditList({ id }: { id: string }) {
  const [audits, setAudits] = useState<Awaited<ReturnType<typeof api.audit>>>([])
  useEffect(() => {
    void api.audit(id).then(setAudits).catch(() => undefined)
  }, [id])
  return (
    <div className="flex flex-col gap-1.5 font-mono text-xs">
      {audits.map((a) => (
        <div key={a.id} className="flex items-center gap-2 py-1 border-b border-border/30 text-muted-foreground">
          <span className="text-[11px] text-muted-foreground/70">{a.ts.slice(11, 19)}</span>
          <span className="font-semibold text-foreground">{a.actor}</span>
          <span>{a.action}</span>
          {a.from_status && <span>({a.from_status} → {a.to_status})</span>}
          {a.reason && <span className="text-foreground/80 truncate">· {a.reason}</span>}
        </div>
      ))}
    </div>
  )
}

function TaskDetail({
  id,
  onClose,
  refresh,
  onOpenSession,
}: {
  id: string
  onClose: () => void
  refresh: () => Promise<void>
  onOpenSession: (sessionId: string) => void
}) {
  const [task, setTask] = useState<Task | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.getTask(id).then(setTask).catch(() => undefined)
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  async function act(
    action:
      | 'approve'
      | 'retry'
      | 'reject'
      | 'unblock'
      | 'approve_plan'
      | 'approve_execution'
      | 'new_session',
  ) {
    setBusy(true)
    setError(null)
    try {
      if (action === 'unblock') await api.unblock(id)
      else if (action === 'new_session') await api.newSession(id)
      else if (action === 'approve_execution') await api.approveExecution(id, note)
      else await api.review(id, action as 'approve' | 'retry' | 'reject' | 'approve_plan', note)
      await load()
      await refresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!task) return null

  const meta = STATUS_META[task.status]
  const needsReview = task.status === 'needs_review'
  const planPending = task.plan_status === 'awaiting_approval'
  const planMeta = PLAN_STATUS_META[task.plan_status] ?? PLAN_STATUS_META.none

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex justify-end animate-in fade-in duration-150">
      <div className="w-full max-w-2xl bg-card border-l border-border h-full flex flex-col shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="p-5 border-b border-border flex items-start justify-between gap-4 bg-muted/20">
          <div className="flex flex-col gap-1.5 min-w-0">
            <h2 className="text-lg font-bold text-foreground leading-tight">{task.title}</h2>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground font-mono">
              <span>{task.id.slice(0, 8)}</span>
              <span>·</span>
              <PriorityBadge priority={task.priority} />
              <RiskBadge risk={task.risk_tier} />
              <span>·</span>
              <span>{task.agent_capability}</span>
            </div>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onClose} className="rounded-full shrink-0">
            <X className="size-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5 text-sm">
          {/* Status & Session Row */}
          <div className="flex flex-col gap-3 p-4 bg-muted/20 border border-border/50 rounded-xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className="font-mono text-xs font-semibold px-2 py-0.5 rounded-md border"
                  style={{
                    borderColor: `${meta.color}40`,
                    backgroundColor: `${meta.color}15`,
                    color: meta.color,
                  }}
                >
                  {meta.label}
                </span>
                <Badge variant="secondary" className="font-mono text-xs">
                  Attempt {task.current_attempt}/{task.max_attempts}
                </Badge>
              </div>
              {task.session_id && (
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => onOpenSession(task.session_id!)}
                  className="gap-1.5 text-xs text-sky-600 dark:text-sky-300 border-sky-500/40 bg-sky-500/10 hover:bg-sky-500/20 font-medium"
                >
                  <MessageSquare className="size-3.5" />
                  Open Live Session
                </Button>
              )}
            </div>

            {task.escalation_reason && (
              <div className="flex items-center gap-2 p-2 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs rounded-md">
                <AlertTriangle className="size-3.5 shrink-0" />
                <span>Escalated: {task.escalation_reason}</span>
              </div>
            )}
          </div>

          {/* Review actions banner if in review */}
          {needsReview && (
            <div className="flex flex-col gap-3 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl">
              <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                {planPending ? 'Plan Review Required' : 'Reviewer Action Required'}
              </span>
              <div className="flex flex-col gap-2">
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Feedback note to the agent (optional)"
                  className="bg-background border border-input rounded-md px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-accent"
                />
                <div className="flex items-center gap-2">
                  {planPending ? (
                    <>
                      <Button
                        size="xs"
                        onClick={() => act('approve_plan')}
                        disabled={busy}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      >
                        Approve Plan → Implement
                      </Button>
                      <Button variant="outline" size="xs" onClick={() => act('retry')} disabled={busy}>
                        Re-plan
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="xs"
                        onClick={() => act('approve')}
                        disabled={busy}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      >
                        Approve
                      </Button>
                      <Button variant="outline" size="xs" onClick={() => act('retry')} disabled={busy}>
                        Retry
                      </Button>
                    </>
                  )}
                  <Button variant="destructive" size="xs" onClick={() => act('reject')} disabled={busy}>
                    Reject
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Backlog action banner */}
          {task.status === 'backlog' && (
            <div className="flex flex-col gap-3 p-4 bg-blue-500/10 border border-blue-500/30 rounded-xl">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
                  Backlog — Human Gate
                </span>
                <span className="text-xs text-muted-foreground">
                  Dispatch task to the agent runner for execution.
                </span>
              </div>
              <Button
                size="sm"
                onClick={() => act('approve_execution')}
                disabled={busy}
                className="w-fit bg-primary text-primary-foreground gap-1.5"
              >
                <Play className="size-3.5" /> Approve for Execution
              </Button>
            </div>
          )}

          {/* CompassX dev host section */}
          {task.compassx_app_id && (
            <div className="flex flex-col gap-3 p-4 bg-muted/20 border border-border/50 rounded-xl">
              <h3 className="text-xs font-semibold text-foreground uppercase tracking-wider flex items-center gap-1.5">
                <Cpu className="size-3.5 text-sky-500 dark:text-sky-400" /> CompassX Dev Environment
              </h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-background/60 p-2.5 rounded-lg border border-border/40 flex flex-col gap-0.5">
                  <span className="text-muted-foreground text-[11px]">App</span>
                  <span className="font-semibold text-foreground">
                    {task.compassx_app_name ?? task.compassx_app_id}
                  </span>
                </div>
                <div className="bg-background/60 p-2.5 rounded-lg border border-border/40 flex flex-col gap-0.5">
                  <span className="text-muted-foreground text-[11px]">Host</span>
                  <span className="font-semibold text-foreground">
                    {task.host_name ?? 'Not provisioned yet'}
                  </span>
                </div>
              </div>

              {task.provisioning_steps && task.provisioning_steps.length > 0 && (
                <div className="flex flex-col gap-1.5 pt-2 border-t border-border/30">
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase">
                    Host Provisioning Pipeline
                  </span>
                  {task.provisioning_steps.map((s) => (
                    <div key={s.name} className="flex items-center justify-between text-xs py-1">
                      <div className="flex items-center gap-2">
                        {s.status === 'done' ? (
                          <CheckCircle2 className="size-3.5 text-emerald-400" />
                        ) : s.status === 'running' ? (
                          <RotateCw className="size-3.5 text-sky-500 dark:text-sky-400 animate-spin" />
                        ) : s.status === 'failed' ? (
                          <AlertCircle className="size-3.5 text-destructive" />
                        ) : (
                          <Clock className="size-3.5 text-muted-foreground" />
                        )}
                        <span className="font-medium text-foreground">
                          {PROVISION_STEP_LABELS[s.name] ?? s.name}
                        </span>
                      </div>
                      <span className="text-[11px] text-muted-foreground font-mono">
                        {timeAgo(s.updated_at)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Intent */}
          <div className="flex flex-col gap-1.5">
            <h3 className="text-xs font-semibold text-foreground uppercase tracking-wider">Intent</h3>
            <p className="text-xs text-muted-foreground bg-muted/20 p-3 rounded-lg border border-border/40">
              {task.intent}
            </p>
          </div>

          {/* Definition of Done */}
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-foreground uppercase tracking-wider">
              Definition of Done
            </h3>
            <div className="flex flex-col gap-1.5">
              {task.criteria.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between p-2.5 bg-muted/20 border border-border/40 rounded-lg text-xs"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'font-bold font-mono text-[11px]',
                        c.result === 'pass'
                          ? 'text-emerald-400'
                          : c.result === 'fail'
                            ? 'text-red-400'
                            : 'text-amber-400',
                      )}
                    >
                      {c.result ?? 'pending'}
                    </span>
                    <span className="text-foreground">{c.description}</span>
                  </div>
                  <Badge variant="outline" className="text-[10px] font-mono">
                    {c.check_type}
                  </Badge>
                </div>
              ))}
            </div>
          </div>

          {/* Attempts */}
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-foreground uppercase tracking-wider">
              Attempts ({task.attempts.length})
            </h3>
            {task.attempts.length === 0 ? (
              <p className="text-xs text-muted-foreground">No attempts executed yet.</p>
            ) : (
              task.attempts.map((a) => (
                <div
                  key={a.id}
                  className="p-3 bg-muted/20 border border-border/40 rounded-lg flex flex-col gap-2 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-foreground">
                      Attempt {a.attempt_number + 1}
                    </span>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {a.status}
                    </Badge>
                  </div>
                  {a.pr_url && (
                    <a
                      href={a.pr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sky-600 dark:text-sky-400 flex items-center gap-1 hover:underline font-medium"
                    >
                      <GitBranch className="size-3" /> Pull Request: {a.pr_url}
                    </a>
                  )}
                  {a.agent_output && (
                    <pre className="text-xs font-mono bg-background p-2.5 rounded border border-border/40 overflow-x-auto max-h-40 whitespace-pre-wrap text-muted-foreground">
                      {a.agent_output}
                    </pre>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Audit trail */}
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-foreground uppercase tracking-wider flex items-center gap-1.5">
              <History className="size-3.5 text-muted-foreground" /> Audit Trail
            </h3>
            <div className="p-3 bg-muted/20 border border-border/40 rounded-lg">
              <AuditList id={task.id} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------- App Router & Topbar
type View = 'board' | 'new' | 'reviews' | 'settings' | 'sessions'

interface RouteState {
  view: View
  selectedTask: string | null
  sessionFocus: string | null
}

function parseLocation(
  pathname = typeof window !== 'undefined' ? window.location.pathname : '/',
  search = typeof window !== 'undefined' ? window.location.search : '',
  rawHash = typeof window !== 'undefined' ? window.location.hash : '',
): RouteState {
  const path = pathname.replace(/\/+$/, '') || '/'
  const hash = rawHash.replace(/^#\/?/, '').replace(/\/+$/, '')
  const params = new URLSearchParams(search)
  const taskParam = params.get('task') || params.get('id') || null
  const focusParam = params.get('focus') || params.get('session') || null

  const effective = (path !== '/' ? path : hash ? `/${hash}` : '/').toLowerCase()

  const taskMatch = effective.match(/^\/(?:tasks?)\/([a-zA-Z0-9_-]+)/)
  if (taskMatch && taskMatch[1] !== 'new') {
    return {
      view: 'board',
      selectedTask: taskMatch[1],
      sessionFocus: focusParam,
    }
  }

  if (effective === '/new' || effective === '/tasks/new') {
    return { view: 'new', selectedTask: null, sessionFocus: null }
  }

  if (effective === '/reviews') {
    return {
      view: 'reviews',
      selectedTask: taskParam,
      sessionFocus: null,
    }
  }

  if (effective.startsWith('/sessions') || effective.startsWith('/c/')) {
    const directSessionMatch = effective.match(/^\/(?:sessions\/c|c)\/([a-zA-Z0-9_.-]+)/)
    const directSessionId = directSessionMatch ? directSessionMatch[1] : null
    return {
      view: 'sessions',
      selectedTask: null,
      sessionFocus: directSessionId || (focusParam !== 'c' ? focusParam : null),
    }
  }

  if (effective === '/settings') {
    return { view: 'settings', selectedTask: null, sessionFocus: null }
  }

  return {
    view: 'board',
    selectedTask: taskParam,
    sessionFocus: focusParam,
  }
}

function buildUrl(view: View, selectedTask: string | null, sessionFocus: string | null): string {
  if (selectedTask) {
    if (view === 'reviews') {
      return `/reviews?task=${encodeURIComponent(selectedTask)}`
    }
    return `/tasks/${encodeURIComponent(selectedTask)}`
  }

  switch (view) {
    case 'new':
      return '/new'
    case 'reviews':
      return '/reviews'
    case 'sessions':
      return sessionFocus && sessionFocus !== 'c'
        ? `/sessions/c/${encodeURIComponent(sessionFocus)}`
        : '/sessions'
    case 'settings':
      return '/settings'
    case 'board':
    default:
      return '/board'
  }
}

export default function AgentBoardApp() {
  const { tasks, metrics, caps, harnessData, error, refresh } = useTaskStore()
  const location = useLocation()
  const navigate = useNavigate()

  const routeState = useMemo(
    () => parseLocation(location.pathname, location.search, location.hash),
    [location.pathname, location.search, location.hash],
  )
  const view = routeState.view
  const selected = routeState.selectedTask
  const sessionFocus = routeState.sessionFocus

  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    return (
      (localStorage.getItem('theme') as 'light' | 'dark') ||
      (localStorage.getItem('app_theme') as 'light' | 'dark') ||
      'dark'
    )
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
    localStorage.setItem('app_theme', theme)
  }, [theme])

  const navigateTo = (
    newView: View,
    newSelected: string | null = null,
    newFocus: string | null = null,
  ) => {
    const targetUrl = buildUrl(newView, newSelected, newFocus)
    navigate(targetUrl)
  }

  const openSession = (sessionId: string) => {
    navigateTo('sessions', null, sessionId)
  }

  const reviewCount = tasks.filter((t) => t.status === 'needs_review').length
  const adapter = caps[0]?.adapter ?? 'omnigent'

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-background text-foreground font-sans antialiased">
      {/* Omnigent-styled Top Header */}
      <header className="h-12 shrink-0 border-b border-border/60 bg-background/95 backdrop-blur-md flex items-center px-4 gap-4 select-none z-30">
        {/* Brand */}
        <div className="flex items-center gap-2.5">
          <div className="size-6 rounded-lg bg-primary flex items-center justify-center text-primary-foreground font-bold text-xs shadow-xs">
            ◧
          </div>
          <span className="font-semibold text-sm tracking-tight text-foreground">TaskExec</span>
        </div>

        {/* Adapter Pill */}
        <Badge
          variant="outline"
          className="hidden sm:inline-flex text-[11px] font-mono px-2 py-0.5 h-5 capitalize border-border/60 text-muted-foreground bg-muted/40 gap-1"
        >
          <Cpu className="size-3" />
          {adapter}
        </Badge>

        {/* Main Navigation Tabs */}
        <nav className="flex items-center gap-1 ml-2">
          <button
            type="button"
            onClick={() => navigateTo('board')}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer',
              view === 'board'
                ? 'bg-secondary text-secondary-foreground shadow-2xs font-semibold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            )}
          >
            <Columns3 className="size-3.5" />
            Board
          </button>
          <button
            type="button"
            onClick={() => navigateTo('new')}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer',
              view === 'new'
                ? 'bg-secondary text-secondary-foreground shadow-2xs font-semibold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            )}
          >
            <PlusCircle className="size-3.5" />
            New Task
          </button>
          <button
            type="button"
            onClick={() => navigateTo('reviews')}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer',
              view === 'reviews'
                ? 'bg-secondary text-secondary-foreground shadow-2xs font-semibold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            )}
          >
            <ClipboardCheck className="size-3.5" />
            Reviews
            {reviewCount > 0 && (
              <Badge
                variant="destructive"
                className="text-[10px] font-mono px-1.5 py-0 h-4 rounded-full ml-1"
              >
                {reviewCount}
              </Badge>
            )}
          </button>
          <button
            type="button"
            onClick={() => navigateTo('sessions', null, null)}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer',
              view === 'sessions'
                ? 'bg-secondary text-secondary-foreground shadow-2xs font-semibold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            )}
          >
            <Bot className="size-3.5 text-sky-500 dark:text-sky-400" />
            Sessions
          </button>
          <button
            type="button"
            onClick={() => navigateTo('settings')}
            className={cn(
              'px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer',
              view === 'settings'
                ? 'bg-secondary text-secondary-foreground shadow-2xs font-semibold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            )}
          >
            <SettingsIcon className="size-3.5" />
            Settings
          </button>
        </nav>

        {/* Right side metrics and theme */}
        <div className="ml-auto flex items-center gap-3">
          {metrics && (
            <div className="hidden md:flex items-center gap-3 text-xs text-muted-foreground bg-muted/40 border border-border/40 rounded-lg px-2.5 py-1">
              <span className="flex items-center gap-1">
                <CheckCircle2 className="size-3 text-emerald-400" />
                {metrics.by_status.done} done
              </span>
              <span className="flex items-center gap-1">
                <Activity className="size-3 text-sky-500 dark:text-sky-400" />
                {metrics.by_status.queued +
                  metrics.by_status.executing +
                  metrics.by_status.verifying}{' '}
                in flight
              </span>
              {metrics.escalation_count > 0 && (
                <span className="flex items-center gap-1 text-amber-400">
                  <AlertTriangle className="size-3" />
                  {metrics.escalation_count} escalated
                </span>
              )}
            </div>
          )}

          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}
            title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
            className="rounded-lg text-muted-foreground hover:text-foreground"
          >
            {theme === 'light' ? <Moon className="size-4" /> : <Sun className="size-4" />}
          </Button>

          <Checkout />
        </div>
      </header>

      {/* Error banner if backend unreachable */}
      {error && (
        <div className="mx-4 mt-3 flex items-center gap-2 p-3 text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-lg">
          <AlertCircle className="size-4 shrink-0" />
          <span>Backend unreachable: {error}</span>
        </div>
      )}

      {/* Main Viewport */}
      <main className="flex-1 min-h-0 flex flex-col overflow-hidden relative">
        {view === 'board' ? (
          <Board tasks={tasks} onClick={(id) => navigateTo('board', id, sessionFocus)} />
        ) : view === 'new' ? (
          <NewTaskForm
            tasks={tasks}
            caps={caps}
            harnessData={harnessData}
            refresh={refresh}
            onCreated={(id) => navigateTo('board', id, sessionFocus)}
          />
        ) : view === 'reviews' ? (
          <Reviews refresh={refresh} onOpen={(id) => navigateTo('reviews', id, sessionFocus)} />
        ) : view === 'sessions' ? (
          <SessionsPage focus={sessionFocus} isDarkMode={theme === 'dark'} />
        ) : (
          <Settings />
        )}
      </main>

      {/* Task detail drawer */}
      {selected && (
        <TaskDetail
          id={selected}
          refresh={refresh}
          onClose={() => navigateTo(view, null, sessionFocus)}
          onOpenSession={openSession}
        />
      )}
    </div>
  )
}