import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@/lib/routing";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Columns3,
  Cpu,
  ExternalLink,
  GitBranch,
  History,
  ListChecks,
  MessageSquare,
  Play,
  PlusCircle,
  RotateCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import type {
  Criterion,
  Metrics,
  Priority,
  RiskTier,
  Task,
} from "@/board/lib/api";
import {
  BOARD_COLUMNS,
  DEFAULT_HARNESS,
  PLAN_STATUS_META,
  PROVISION_STEP_LABELS,
  STATUS_META,
  api,
  readStream,
  timeAgo,
} from "@/board/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageScroll } from "@/components/PageScroll";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------------------- Priority & Risk Badges
function PriorityBadge({ priority }: { priority: string }) {
  const variants: Record<string, string> = {
    urgent: "border-red-500/40 text-red-400 bg-red-500/10 font-semibold",
    high: "border-amber-500/40 text-amber-400 bg-amber-500/10 font-semibold",
    normal: "border-sky-500/40 text-sky-400 bg-sky-500/10 font-semibold",
    low: "border-slate-500/40 text-slate-300 bg-slate-500/10 font-semibold",
  }
  return (
    <Badge
      variant="outline"
      className={cn("text-[11px] font-mono capitalize px-1.5 py-0 h-4.5", variants[priority] || "")}
    >
      {priority}
    </Badge>
  )
}

function RiskBadge({ risk }: { risk: string }) {
  const variants: Record<string, string> = {
    high: "border-red-500/40 text-red-400 bg-red-500/10 font-semibold",
    medium: "border-amber-500/40 text-amber-400 bg-amber-500/10 font-semibold",
    low: "border-emerald-500/40 text-emerald-400 bg-emerald-500/10 font-semibold",
  }
  return (
    <Badge
      variant="outline"
      className={cn("text-[11px] font-mono capitalize px-1.5 py-0 h-4.5", variants[risk] || "")}
    >
      {risk} risk
    </Badge>
  )
}

function StatusDot({ status }: { status: string }) {
  const meta = STATUS_META[status] || { color: "#94a3b8", label: status, badgeClass: "" }
  return (
    <span
      className="size-2 rounded-full inline-block shrink-0 shadow-xs"
      style={{ backgroundColor: meta.color }}
    />
  )
}

// -------------------------------------------------------------------- Task Card
function TaskCard({ task, onClick }: { task: Task; onClick: (id: string) => void }) {
  const meta = STATUS_META[task.status] || { color: "#94a3b8", label: task.status, badgeClass: "border-slate-500/40 text-slate-300 bg-slate-500/10" }
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onClick(task.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onClick(task.id)
        }
      }}
      className="group relative flex flex-col gap-2.5 p-3.5 bg-card hover:bg-card-solid border border-border/70 hover:border-border-strong rounded-xl shadow-2xs hover:shadow-xs transition-all cursor-pointer text-left select-none"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-[13.5px] leading-snug text-foreground group-hover:text-primary transition-colors line-clamp-2">
          {task.title}
        </span>
        <span
          className={cn(
            "text-[11px] font-semibold font-mono shrink-0 px-2 py-0.5 rounded-md border",
            meta.badgeClass,
          )}
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
          title={`Harness / Adapter: ${task.harness || DEFAULT_HARNESS}`}
        >
          <Cpu className="size-2.5 text-sky-500 dark:text-sky-400" />
          <span>{task.harness || DEFAULT_HARNESS}</span>
        </Badge>
        {task.compassx_app_name && (
          <Badge
            variant="outline"
            className="text-[11px] font-mono px-1.5 py-0 h-4.5 border-status-green/30 text-status-green bg-status-green/10 flex items-center gap-1 font-medium"
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
            variant="outline"
            className="text-[11px] font-mono px-1.5 py-0 h-4.5 border-status-red/40 text-status-red bg-status-red/10 flex items-center gap-1"
          >
            <AlertTriangle className="size-2.5" />
            escalated
          </Badge>
        )}
      </div>

      <div className="flex items-center justify-between text-[11.5px] text-muted-foreground pt-1 border-t border-border/30">
        <span className="truncate max-w-[140px] font-mono">{task.agent_capability}</span>
        <span className="flex items-center gap-1 shrink-0 font-mono text-[11px]">
          <Clock className="size-3" />
          {timeAgo(task.updated_at)}
        </span>
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

function TaskDetailDrawer({
  id,
  onClose,
  refresh,
}: {
  id: string
  onClose: () => void
  refresh: () => Promise<void>
}) {
  const navigate = useNavigate()
  const [task, setTask] = useState<Task | null>(null)
  const [note, setNote] = useState("")
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
      | "approve"
      | "retry"
      | "reject"
      | "unblock"
      | "approve_plan"
      | "approve_execution"
      | "new_session",
  ) {
    setBusy(true)
    setError(null)
    try {
      if (action === "unblock") await api.unblock(id)
      else if (action === "new_session") await api.newSession(id)
      else if (action === "approve_execution") await api.approveExecution(id, note)
      else await api.review(id, action as "approve" | "retry" | "reject" | "approve_plan", note)
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
  const needsReview = task.status === "needs_review"
  const planPending = task.plan_status === "awaiting_approval"

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
              <Badge variant="outline" className="text-[11px] font-mono px-1.5 py-0 h-4.5 border-border/60">
                {task.agent_capability}
              </Badge>
              <Badge
                variant="outline"
                className="text-[11px] font-mono px-1.5 py-0 h-4.5 border-sky-500/40 text-sky-600 dark:text-sky-300 bg-sky-500/10 flex items-center gap-1 font-medium"
                title="Harness / Adapter"
              >
                <Cpu className="size-2.5 text-sky-500 dark:text-sky-400" />
                <span>{task.harness || DEFAULT_HARNESS}</span>
              </Badge>
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
                  className={cn(
                    "font-mono text-xs font-semibold px-2.5 py-0.5 rounded-md border",
                    meta.badgeClass,
                  )}
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
                  onClick={() => navigate(`/c/${task.session_id}`)}
                  className="gap-1.5 text-xs text-sky-600 dark:text-sky-300 border-sky-500/40 bg-sky-500/10 hover:bg-sky-500/20 font-medium"
                >
                  <MessageSquare className="size-3.5" />
                  Open Live Session
                </Button>
              )}
            </div>

            {task.escalation_reason && (
              <div className="flex items-center gap-2 p-2.5 bg-status-red/10 border border-status-red/30 text-status-red text-xs rounded-lg">
                <AlertTriangle className="size-3.5 shrink-0" />
                <span>Escalated: {task.escalation_reason}</span>
              </div>
            )}
          </div>

          {/* Review actions banner if in review */}
          {needsReview && (
            <div className="flex flex-col gap-3 p-4 bg-status-yellow/10 border border-status-yellow/30 rounded-xl">
              <span className="text-xs font-semibold text-status-yellow uppercase tracking-wider">
                {planPending ? "Plan Review Required" : "Reviewer Action Required"}
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
                        onClick={() => act("approve_plan")}
                        disabled={busy}
                        className="bg-status-green hover:bg-status-green/90 text-white font-medium"
                      >
                        Approve Plan → Implement
                      </Button>
                      <Button variant="outline" size="xs" onClick={() => act("retry")} disabled={busy}>
                        Re-plan
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="xs"
                        onClick={() => act("approve")}
                        disabled={busy}
                        className="bg-status-green hover:bg-status-green/90 text-white font-medium"
                      >
                        Approve
                      </Button>
                      <Button variant="outline" size="xs" onClick={() => act("retry")} disabled={busy}>
                        Retry
                      </Button>
                    </>
                  )}
                  <Button variant="destructive" size="xs" onClick={() => act("reject")} disabled={busy}>
                    Reject
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Backlog action banner */}
          {task.status === "backlog" && (
            <div className="flex flex-col gap-3 p-4 bg-sky-500/10 border border-sky-500/30 rounded-xl">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-sky-400 uppercase tracking-wider">
                  Backlog — Human Gate
                </span>
                <span className="text-xs text-muted-foreground">
                  Dispatch task to the agent runner for execution.
                </span>
              </div>
              <Button
                size="sm"
                onClick={() => act("approve_execution")}
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
                    {task.host_name ?? "Not provisioned yet"}
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
                        {s.status === "done" ? (
                          <CheckCircle2 className="size-3.5 text-status-green" />
                        ) : s.status === "running" ? (
                          <RotateCw className="size-3.5 text-sky-500 dark:text-sky-400 animate-spin" />
                        ) : s.status === "failed" ? (
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
                        "font-bold font-mono text-[11px]",
                        c.result === "pass"
                          ? "text-status-green"
                          : c.result === "fail"
                            ? "text-status-red"
                            : "text-status-yellow",
                      )}
                    >
                      {c.result ?? "pending"}
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

// ------------------------------------------------------------------------ Main Board Page
export function BoardPage() {
  const { taskId } = useParams<{ taskId?: string }>()
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedTask, setSelectedTask] = useState<string | null>(taskId ?? null)

  useEffect(() => {
    if (taskId) setSelectedTask(taskId)
  }, [taskId])

  const refresh = useCallback(async () => {
    try {
      const [t, m] = await Promise.all([api.listTasks(), api.metrics()])
      setTasks(t)
      setMetrics(m)
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
    <div className="flex flex-col flex-1 h-full w-full min-h-0 bg-background overflow-hidden">
      {/* Board Header Bar */}
      <div className="p-4 border-b border-border/60 bg-background flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Columns3 className="size-5 text-primary" />
            <h1 className="text-lg font-semibold tracking-tight text-foreground">Task Board</h1>
          </div>
          {metrics && (
            <div className="hidden sm:flex items-center gap-2.5 text-xs text-muted-foreground bg-muted/40 border border-border/40 rounded-lg px-2.5 py-1">
              <span className="flex items-center gap-1">
                <CheckCircle2 className="size-3 text-status-green" />
                {metrics.by_status.done} done
              </span>
              <span className="flex items-center gap-1">
                <Activity className="size-3 text-sky-500 dark:text-sky-400" />
                {metrics.by_status.queued +
                  metrics.by_status.executing +
                  metrics.by_status.verifying}{" "}
                in flight
              </span>
              {metrics.escalation_count > 0 && (
                <span className="flex items-center gap-1 text-status-yellow">
                  <AlertTriangle className="size-3" />
                  {metrics.escalation_count} escalated
                </span>
              )}
              {metrics.adapter && (
                <span className="flex items-center gap-1.5 border-l border-border/60 pl-2.5 font-mono text-xs">
                  <Cpu className="size-3 text-sky-500 dark:text-sky-400" />
                  <span className="text-muted-foreground">adapter:</span>
                  <span className="font-semibold px-1.5 py-0.5 rounded text-[11px] uppercase tracking-wide bg-sky-500/15 text-sky-600 dark:text-sky-300 border border-sky-500/30">
                    {metrics.adapter}
                  </span>
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button asChild size="sm" className="gap-1.5">
            <Link to="/new">
              <PlusCircle className="size-3.5" />
              New Task
            </Link>
          </Button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mt-3 flex items-center gap-2 p-3 text-xs bg-destructive/10 border border-destructive/30 text-destructive rounded-lg">
          <AlertCircle className="size-4 shrink-0" />
          <span>Backend unreachable: {error}</span>
        </div>
      )}

      {/* Kanban Columns */}
      <div className="flex-1 flex gap-3.5 p-4 overflow-x-auto min-h-0 bg-background/50">
        {BOARD_COLUMNS.map((status) => {
          const columnTasks = byStatus[status] || []
          const meta = STATUS_META[status] || { color: "var(--status-gray, #8e8e93)", label: status }
          return (
            <div
              key={status}
              className="w-72 shrink-0 bg-muted/20 backdrop-blur-xs border border-border/60 rounded-xl flex flex-col max-h-full overflow-hidden shadow-2xs"
            >
              <div className="p-3 border-b border-border/40 flex items-center justify-between font-semibold text-xs tracking-wider uppercase text-muted-foreground bg-muted/30">
                <div className="flex items-center gap-2">
                  <StatusDot status={status} />
                  <span className="text-foreground/90">{meta.label}</span>
                </div>
                <Badge
                  variant="secondary"
                  className="text-[11px] font-mono px-1.5 py-0 h-5 rounded-full bg-muted text-muted-foreground border border-border/40"
                >
                  {columnTasks.length}
                </Badge>
              </div>
              <div className="p-2.5 overflow-y-auto flex-1 flex flex-col gap-2.5">
                {columnTasks.map((t) => (
                  <TaskCard key={t.id} task={t} onClick={(id) => setSelectedTask(id)} />
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

      {/* Task detail drawer */}
      {selectedTask && (
        <TaskDetailDrawer
          id={selectedTask}
          refresh={refresh}
          onClose={() => setSelectedTask(null)}
        />
      )}
    </div>
  )
}
