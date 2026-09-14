import { useCallback, useEffect, useMemo, useState } from 'react'
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
import { BOARD_COLUMNS, DEFAULT_HARNESS, PLAN_STATUS_META, PROVISION_STEP_LABELS, STATUS_META, readStream, timeAgo, api } from './lib/api'
import Checkout from './components/Checkout'
import './App.css'

// ------------------------------------------------------------------------- data
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

// ------------------------------------------------------------------------ bits
const PRIORITY_CLASS: Record<string, string> = {
  low: 'p-low',
  normal: 'p-normal',
  high: 'p-high',
  urgent: 'p-urgent',
}
const RISK_CLASS: Record<string, string> = {
  low: 'r-low',
  medium: 'r-medium',
  high: 'r-high',
}

function Chip({
  children,
  className = '',
  style,
  title,
}: {
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
  title?: string
}) {
  return (
    <span className={`chip ${className}`} style={style} title={title}>
      {children}
    </span>
  )
}

function Empty({ text }: { text: string }) {
  return <p className="empty">{text}</p>
}

function ErrorBanner({ message }: { message: string }) {
  return <div className="error-banner">⚠ {message}</div>
}

// -------------------------------------------------------------------- task card
function TaskCard({ task, onClick }: { task: Task; onClick: (id: string) => void }) {
  const meta = STATUS_META[task.status]
  return (
    <button className="task-card" onClick={() => onClick(task.id)} style={{ borderTopColor: meta.color }}>
      <div className="task-card-head">
        <span className="task-title">{task.title}</span>
        <span className="task-status" style={{ color: meta.color }}>
          {meta.label}
        </span>
      </div>
      <div className="task-card-meta">
        <Chip className={PRIORITY_CLASS[task.priority]}>{task.priority}</Chip>
        <Chip className={RISK_CLASS[task.risk_tier]}>{task.risk_tier}</Chip>
        <Chip className="harness-chip" title="omnigent harness">{task.harness || DEFAULT_HARNESS}</Chip>
        {task.compassx_app_name && <Chip className="app-chip" title="CompassX app">{task.compassx_app_name}</Chip>}
        {task.host_name && <Chip title="execution host">{task.host_name}</Chip>}
        <Chip>attempt {task.current_attempt + (task.status === 'executing' || task.status === 'verifying' ? 1 : 0)}/{task.max_attempts}</Chip>
        {task.escalation_reason && <Chip className="r-high">escalated</Chip>}
        {task.session_id && <Chip title="agent session">⚡ {task.session_id}</Chip>}
      </div>
      <div className="task-card-foot">
        <span>{task.agent_capability}</span>
        <span>{timeAgo(task.updated_at)}</span>
      </div>
    </button>
  )
}

// ------------------------------------------------------------------------ board
function Board({ tasks, onClick }: { tasks: Task[]; onClick: (id: string) => void }) {
  const byStatus = useMemo(() => {
    const map: Record<string, Task[]> = { backlog: [], queued: [], host_provisioning: [], executing: [], verifying: [], needs_review: [], done: [], rejected: [], blocked: [] }
    for (const t of tasks) if (map[t.status]) map[t.status].push(t)
    return map
  }, [tasks])

  return (
    <div className="board">
      {BOARD_COLUMNS.map((status) => (
        <div className="column" key={status}>
          <div className="column-head">
            <span className="dot" style={{ background: STATUS_META[status].color }} />
            <span>{STATUS_META[status].label}</span>
            <span className="count">{byStatus[status].length}</span>
          </div>
          <div className="column-body">
            {byStatus[status].map((t) => (
              <TaskCard key={t.id} task={t} onClick={onClick} />
            ))}
            {byStatus[status].length === 0 && <Empty text="No tasks" />}
          </div>
        </div>
      ))}
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
    { description: 'Agent output indicates success', check_type: 'output_match', check_config: '{"pattern": "success"}' },
  ])
  const [context, setContext] = useState<ContextDraft[]>([])
  const [conversation, setConversation] = useState('')
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // CompassX app binding: pick the app the task runs against; a remote dev
  // host for that app is spun up (or resumed) automatically at execution time.
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
        criteria: criteria.filter((c) => c.description.trim()).map((c) => {
          let cfg = {}
          try {
            cfg = c.check_config.trim() ? JSON.parse(c.check_config) : {}
          } catch {
            cfg = { _malformed: c.check_config }
          }
          return { description: c.description.trim(), check_type: c.check_type as Criterion['check_type'], check_config: cfg }
        }),
      }
      if (!payload.title) throw new Error('title is required')
      if (!payload.criteria.length) throw new Error('at least one definition-of-done criterion is required')
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
    <div className="page">
      <h2>New task</h2>

      <section className="panel">
        <h3>Conversational creation</h3>
        <p className="muted">Describe the task in plain language and let the parser suggest structured fields.</p>
        <div className="row">
          <input
            value={conversation}
            onChange={(e) => setConversation(e.target.value)}
            placeholder='e.g. "URGENT: apply the security patch to production, needs sign-off"'
          />
          <button type="button" onClick={parseIt} disabled={parsing || !conversation.trim()}>
            {parsing ? 'Parsing…' : 'Parse'}
          </button>
        </div>
      </section>

      <form onSubmit={submit} className="panel">
        <div className="field">
          <label>Title *</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Short, action-first title" />
        </div>
        <div className="field">
          <label>Intent</label>
          <textarea value={intent} onChange={(e) => setIntent(e.target.value)} rows={3} placeholder="Plain-language desired outcome" />
        </div>

        <div className="grid">
          <div className="field">
            <label>Priority</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
              <option value="low">low</option>
              <option value="normal">normal</option>
              <option value="high">high</option>
              <option value="urgent">urgent</option>
            </select>
          </div>
          <div className="field">
            <label>Risk tier</label>
            <select value={risk} onChange={(e) => setRisk(e.target.value as RiskTier)}>
              <option value="low">low — auto-approve</option>
              <option value="medium">medium — auto-approve</option>
              <option value="high">high — requires sign-off</option>
            </select>
          </div>
          <div className="field">
            <label>Agent capability</label>
            <select value={capability} onChange={(e) => setCapability(e.target.value)}>
              {caps.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Harness (agent engine)</label>
            <select value={harness} onChange={(e) => setHarness(e.target.value)}>
              {(harnessData?.harnesses ?? []).map((h) => (
                <option key={h.name} value={h.name}>
                  {h.name}
                  {h.name === harnessData?.default ? ' (default)' : ''}
                </option>
              ))}
              {!harnessData && <option value={harness}>{harness}</option>}
            </select>
            <p className="muted">
              Resolved to its current agent on the Omnigent server at execution time.
            </p>
          </div>
        </div>

        <div className="field">
          <label>CompassX app (remote dev host is spun up at execution)</label>
          <select value={appId} onChange={(e) => setAppId(e.target.value)}>
            <option value="">— none (run on the local default host) —</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} {a.git_branch ? `(${a.git_branch})` : ''}
              </option>
            ))}
          </select>
          {appsError && <p className="muted warn">{appsError}</p>}
          {apps.length === 0 && !appsError && appId === '' && (
            <p className="muted">CompassX not configured on the backend — apps cannot be listed.</p>
          )}
          {appId !== '' && (
            <div className="row">
              <label className="checkbox-label">
                <input type="checkbox" checked={reuseWorkspace} onChange={(e) => setReuseWorkspace(e.target.checked)} />
                Reuse an existing dev workspace (redo task)
              </label>
              {reuseWorkspace && (
                <select value={appWsId} onChange={(e) => setAppWsId(e.target.value)}>
                  <option value="">— create a fresh workspace —</option>
                  {appWorkspaces.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name || w.id} ({w.folder_path})
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
          <p className="muted">
            Bound tasks start a Kubernetes dev pod for the app, verify the host is online in the
            Omnigent server, then run the agent there.
          </p>
        </div>

        <div className="field plan-toggle">
          <label>
            <input type="checkbox" checked={planRequired} onChange={(e) => setPlanRequired(e.target.checked)} />
            Require an implementation plan (agent plans first → you approve → agent implements → PR)
          </label>
        </div>

        <div className="field">
          <label className="checkbox-label">
            <input type="checkbox" checked={bypassVerification} onChange={(e) => setBypassVerification(e.target.checked)} />
            Bypass verification (skip definition-of-done checks)
          </label>
          {bypassVerification && (
            <div className="row">
              <select value={bypassOutcome} onChange={(e) => setBypassOutcome(e.target.value)}>
                <option value="needs_review">When agent finishes → requires review (default)</option>
                <option value="done">When agent finishes → mark done</option>
              </select>
              <p className="muted">Criteria are not evaluated; the finished task routes straight to the chosen outcome.</p>
            </div>
          )}
        </div>

        <div className="field">
          <label>Workspace (host path to the app/repo; blank = default)</label>
          <input
            placeholder="/workspaces/.../frontend — e.g. the app you want changed"
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
          />
        </div>

        <div className="field">
          <label>Dependencies (must complete first)</label>
          <select multiple value={deps} onChange={(e) => setDeps(Array.from(e.target.selectedOptions).map((o) => o.value))}>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                [{t.status}] {t.title}
              </option>
            ))}
          </select>
          <p className="muted">Hold Ctrl/Cmd to select multiple.</p>
        </div>

        <div className="field">
          <label>Context references</label>
          {context.map((c, i) => (
            <div className="row context-row" key={i}>
              <select value={c.type} onChange={(e) => setContext(context.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}>
                <option value="link">link</option>
                <option value="file">file</option>
                <option value="dataset">dataset</option>
                <option value="prior_task_output">prior_task_output</option>
              </select>
              <input
                value={c.ref}
                onChange={(e) => setContext(context.map((x, j) => (j === i ? { ...x, ref: e.target.value } : x)))}
                placeholder="ref (url, path, …)"
              />
              <input
                value={c.description}
                onChange={(e) => setContext(context.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                placeholder="description"
              />
              <button type="button" className="danger" onClick={() => setContext(context.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
          ))}
          <button type="button" className="ghost" onClick={() => setContext([...context, { type: 'link', ref: '', description: '' }])}>
            + Add context
          </button>
        </div>

        <div className="field">
          <label>Definition of done *</label>
          {criteria.map((c, i) => (
            <div className="panel criterion-row" key={i}>
              <input
                value={c.description}
                onChange={(e) => setCriteria(criteria.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                placeholder="Criterion description"
              />
              <select value={c.check_type} onChange={(e) => setCriteria(criteria.map((x, j) => (j === i ? { ...x, check_type: e.target.value } : x)))}>
                {Object.entries(CHECK_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              {c.check_type !== 'human_approval' && c.check_type !== 'manual_checklist' && (
                <input
                  value={c.check_config}
                  onChange={(e) => setCriteria(criteria.map((x, j) => (j === i ? { ...x, check_config: e.target.value } : x)))}
                  placeholder={CHECK_HINT[c.check_type]}
                />
              )}
              <button type="button" className="danger" onClick={() => setCriteria(criteria.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            className="ghost"
            onClick={() =>
              setCriteria([...criteria, { description: '', check_type: 'output_match', check_config: '{"pattern": "success"}' }])
            }
          >
            + Add criterion
          </button>
        </div>

        {error && <ErrorBanner message={error} />}
        <div className="row end">
          <button type="submit" disabled={saving}>
            {saving ? 'Creating…' : 'Create task'}
          </button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------- reviews
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
    <div className="page">
      <h2>Review queue</h2>
      {error && <ErrorBanner message={error} />}
      {items.length === 0 ? (
        <Empty text="No tasks awaiting review" />
      ) : (
        items.map((t) => (
          <section className="panel" key={t.id}>
            <div className="review-head">
              <button className="link" onClick={() => onOpen(t.id)}>
                <strong>{t.title}</strong>
              </button>
              <Chip className={RISK_CLASS[t.risk_tier]}>risk: {t.risk_tier}</Chip>
              {t.plan_required && <Chip className="r-medium">plan-first</Chip>}
              <Chip className="r-high">attempt {t.current_attempt}/{t.max_attempts}</Chip>
            </div>
            {t.escalation_reason && <p className="reason">⏫ {t.escalation_reason}</p>}

            {t.plan_status === 'awaiting_approval' ? (
              <div className="plan-block">
                <h4>Proposed implementation plan</h4>
                <pre className="plan-text">{t.plan_text ?? '(plan produced, open task for details)'}</pre>
              </div>
            ) : (
              <div className="criteria-list">
                {t.criteria.map((c) => (
                  <div className="criterion-line" key={c.id}>
                    <span className={`v-${c.result ?? 'pending'}`}>{c.result ?? 'pending'}</span>
                    <span>{c.description}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="row">
              <input
                value={notes[t.id] ?? ''}
                onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })}
                placeholder={t.plan_status === 'awaiting_approval' ? 'Note to the agent (optional)' : 'Reviewer note'}
              />
              {t.plan_status === 'awaiting_approval' ? (
                <>
                  <button className="ok" disabled={busy === t.id} onClick={() => act(t.id, 'approve_plan')}>
                    Approve plan → implement
                  </button>
                  <button disabled={busy === t.id} onClick={() => act(t.id, 'retry')}>
                    Re-plan
                  </button>
                  <button disabled={busy === t.id} onClick={() => act(t.id, 'reject')}>
                    Reject
                  </button>
                </>
              ) : (
                <>
                  <button className="ok" disabled={busy === t.id} onClick={() => act(t.id, 'approve')}>
                    Approve
                  </button>
                  <button disabled={busy === t.id} onClick={() => act(t.id, 'retry')}>
                    Retry
                  </button>
                  <button disabled={busy === t.id} onClick={() => act(t.id, 'reject')}>
                    Reject
                  </button>
                </>
              )}
            </div>
          </section>
        ))
      )}
    </div>
  )
}

// ------------------------------------------------------------------ settings
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
    return <div className="panel"><Empty text={error ?? 'Loading settings…'} /></div>
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
    <div>
      <h2>Settings</h2>
      <div className="panel settings-panel">
        {entries.length === 0 && <Empty text="No managed settings yet" />}
        {entries.map(([key, def]) => {
          const current = String(data.settings[key] ?? '')
          const dirty = (draft[key] ?? '') !== current
          return (
            <div className="setting-row" key={key}>
              <div className="setting-meta">
                <strong>{def.label}</strong>
                {def.description && <p className="muted">{def.description}</p>}
              </div>
              <div className="setting-input">
                {def.type === 'number' ? (
                  <input
                    type="number"
                    value={draft[key] ?? ''}
                    min={def.min}
                    max={def.max}
                    step={def.step}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  />
                ) : (
                  <input
                    value={draft[key] ?? ''}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  />
                )}
                {dirty && <span className="badge">unsaved</span>}
              </div>
            </div>
          )
        })}
        {error && <div className="banner-error">{error}</div>}
        <div className="row settings-actions">
          <button className="link" onClick={() => reload()} disabled={saved}>
            Reset
          </button>
          <button className="ok" onClick={() => void save()} disabled={saved}>
            {saved ? `Saved ✓` : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ task detail
function AuditList({ id }: { id: string }) {
  const [audits, setAudits] = useState<Awaited<ReturnType<typeof api.audit>>>([])
  useEffect(() => {
    void api.audit(id).then(setAudits).catch(() => undefined)
  }, [id])
  return (
    <div className="audit-list">
      {audits.map((a) => (
        <div className="audit-row" key={a.id}>
          <code>{a.ts.slice(0, 19).replace('T', ' ')}</code>
          <span className="audit-actor">{a.actor}</span>
          <span>{a.action}</span>
          {a.from_status && <span> {a.from_status} → </span>}
          {a.to_status && <strong>{a.to_status}</strong>}
          <span className="muted">{a.reason ? `· ${a.reason}` : ''}</span>
        </div>
      ))}
    </div>
  )
}

function TaskDetail({
  id,
  onClose,
  refresh,
}: {
  id: string
  onClose: () => void
  refresh: () => Promise<void>
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

  async function act(action: 'approve' | 'retry' | 'reject' | 'unblock' | 'approve_plan' | 'approve_execution' | 'new_session') {
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

  if (!task) return <div className="overlay-backdrop" />

  const meta = STATUS_META[task.status]
  const needsReview = task.status === 'needs_review'
  const planPending = task.plan_status === 'awaiting_approval'
  const planMeta = PLAN_STATUS_META[task.plan_status] ?? PLAN_STATUS_META.none

  return (
    <div className="overlay">
      <div className="drawer">
        <div className="drawer-head">
          <div>
            <h2>{task.title}</h2>
            <p className="muted">
              {task.id.slice(0, 8)} · {task.priority} · risk {task.risk_tier} · {task.agent_capability} · harness{' '}
              <code>{task.harness || DEFAULT_HARNESS}</code> · workspace{' '}
              <code>{task.workspace ?? 'default'}</code> ·{' '}
              {task.bypass_verification ? <span className="muted">verification bypassed → {task.verification_bypass_outcome}</span> : <span className="muted">verification on</span>}{' '}
              · created {timeAgo(task.created_at)} by {task.created_by}
            </p>
          </div>
          <button className="ghost" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="drawer-body">
          <section className="panel">
            <div className="status-row">
              <Chip className="status-big" style={{ color: meta.color }}>{meta.label}</Chip>
              <Chip>attempt {task.current_attempt}/{task.max_attempts}</Chip>
              {task.escalation_reason && <Chip className="r-high">⏫ escalated</Chip>}
            </div>
            {task.escalation_reason && <p className="reason">Reason: {task.escalation_reason}</p>}

            {task.session_id && (
              <div className="session-id-line">
                <Chip className="r-medium">{task.session_provider ?? 'agent'} session</Chip>
                {task.session_status && (
                  <Chip className={`session-state session-state-${task.session_status}`} title="live session status">
                    {task.session_status}
                  </Chip>
                )}
                <code>{task.session_id}</code>
                {task.session_link ? (
                  <a href={task.session_link} target="_blank" rel="noreferrer">
                    open
                  </a>
                ) : null}
                <button className="ghost" disabled={busy} onClick={() => act('new_session')}>
                  New session
                </button>
              </div>
            )}

            {task.compassx_app_id && (
              <div className="compassx-block">
                <h3>CompassX dev environment</h3>
                <div className="meta-grid">
                  <div>
                    <span className="muted">app</span>
                    <strong>{task.compassx_app_name ?? task.compassx_app_id}</strong>
                  </div>
                  <div>
                    <span className="muted">host</span>
                    <strong>{task.host_name ?? 'not provisioned yet'}</strong>
                    {task.host_id && <code> · {task.host_id.slice(0, 12)}…</code>}
                  </div>
                  <div>
                    <span className="muted">workspace</span>
                    <code>{task.workspace ?? 'new workspace on start'}</code>
                  </div>
                  <div>
                    <span className="muted">workspace name</span>
                    <code>{task.compassx_workspace_name ?? 'created on start'}</code>
                  </div>
                  <div>
                    <span className="muted">publish</span>
                    <strong>{task.compassx_published ? '✓ committed & pushed' : 'pending completion'}</strong>
                  </div>
                </div>
                {task.dev_url && (
                  <p>
                    <a href={task.dev_url} target="_blank" rel="noreferrer">
                      🔗 Open dev environment
                    </a>
                  </p>
                )}
                {task.provisioning_steps && task.provisioning_steps.length > 0 && (
                  <div className="provision-steps">
                    <h4>Host provisioning steps</h4>
                    {task.provisioning_steps.map((s) => (
                      <div className={`provision-step ps-${s.status}`} key={s.name}>
                        <span className="ps-icon">
                          {s.status === 'done' ? '✓' : s.status === 'failed' ? '✕' : s.status === 'running' ? '⟳' : '○'}
                        </span>
                        <span className="ps-label">{PROVISION_STEP_LABELS[s.name] ?? s.name}</span>
                        {s.detail && <code className="ps-detail">{s.detail}</code>}
                        <span className="ps-time">{timeAgo(s.updated_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {task.plan_required && (
              <section className="plan-detail">
                <h3>
                  Implementation plan{' '}
                  <Chip style={{ color: planMeta.color }}>{planMeta.label}</Chip>
                </h3>
                {task.plan_text ? (
                  <pre className="plan-text">{task.plan_text}</pre>
                ) : (
                  <p className="muted">
                    {task.plan_status === 'none'
                      ? 'No plan yet — the agent will produce one before any code changes.'
                      : 'The agent is working on a plan…'}
                  </p>
                )}
                {task.pr_url && (
                  <p>
                    <a href={task.pr_url} target="_blank" rel="noreferrer">
                      🔗 Pull request: {task.pr_url}
                    </a>
                  </p>
                )}
              </section>
            )}

            <h3>Intent</h3>
            <p>{task.intent}</p>

            <h3>Definition of done</h3>
            <div className="criteria-list">
              {task.criteria.map((c) => (
                <div className="criterion-line" key={c.id}>
                  <span className={`v-${c.result ?? 'pending'}`}>{c.result ?? 'pending'}</span>
                  <span className="flex-1">
                    {c.description} <span className="muted">({c.check_type})</span>
                  </span>
                  {c.detail && <code className="muted">{c.detail}</code>}
                </div>
              ))}
            </div>

            <h3>Context</h3>
            {task.context.length === 0 ? (
              <p className="muted">None</p>
            ) : (
              <ul className="context-list">
                {task.context.map((c) => (
                  <li key={c.id}>
                    <Chip>{c.type}</Chip> {c.ref} {c.description ? <span className="muted">· {c.description}</span> : null}
                  </li>
                ))}
              </ul>
            )}

            <h3>Attempts</h3>
            {task.attempts.length === 0 ? <p className="muted">No attempts yet.</p> : null}
            {task.attempts.map((a) => (
              <div className="attempt" key={a.id}>
                <div className="attempt-head">
                  <strong>Attempt {a.attempt_number + 1}</strong>
                  <Chip>{a.status}</Chip>
                  {a.phase && a.phase !== 'execute' && <Chip className="r-medium">{a.phase}</Chip>}
                  <Chip>verify: {a.verification_result ?? '—'}</Chip>
                  <span className="muted">{timeAgo(a.finished_at ?? a.started_at)}</span>
                </div>
                {a.failure_reason && <p className="reason">failure: {a.failure_reason}</p>}
                {a.pr_url && (
                  <p>
                    <a href={a.pr_url} target="_blank" rel="noreferrer">
                      🔗 PR: {a.pr_url}
                    </a>
                  </p>
                )}
                <details>
                  <summary>agent output</summary>
                  <pre className="output">{a.agent_output}</pre>
                </details>
                {a.tools_used.length > 0 && (
                  <p className="muted">
                    tools: {a.tools_used.join(', ')}
                    {a.logs_ref ? ` · logs: ${a.logs_ref}` : ''}
                  </p>
                )}
                {a.verification_details && <p className="muted">verification: {a.verification_details}</p>}
              </div>
            ))}

            <h3>Sessions</h3>
            {(task.sessions ?? []).length === 0 ? <p className="muted">No agent sessions yet.</p> : null}
            {(task.sessions ?? []).map((s) => (
              <div className="session" key={s.id}>
                <div className="session-head">
                  <Chip>{s.provider}</Chip>
                  <code className="session-id">{s.session_id}</code>
                  {s.status && <Chip className={`session-state session-state-${s.status}`}>{s.status}</Chip>}
                  {s.archived ? (
                    <Chip className="muted-chip">archived</Chip>
                  ) : (
                    <Chip className="active-chip">active</Chip>
                  )}
                  <span className="muted">{timeAgo(s.created_at)}</span>
                </div>
                {s.link ? (
                  <p><a href={s.link} target="_blank" rel="noreferrer">🔗 open session</a></p>
                ) : (
                  <p className="muted">no link recorded</p>
                )}
              </div>
            ))}

            <h3>Audit trail</h3>
            <AuditList id={task.id} />
          </section>

          {needsReview && (
            <section className="panel review-panel">
              <h3>{planPending ? 'Plan review' : 'Reviewer action'}</h3>
              <div className="row">
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" />
                {planPending ? (
                  <>
                    <button className="ok" disabled={busy} onClick={() => act('approve_plan')}>
                      Approve plan → implement
                    </button>
                    <button disabled={busy} onClick={() => act('retry')}>
                      Re-plan
                    </button>
                  </>
                ) : (
                  <>
                    <button className="ok" disabled={busy} onClick={() => act('approve')}>
                      Approve
                    </button>
                    <button disabled={busy} onClick={() => act('retry')}>
                      Retry with note
                    </button>
                  </>
                )}
                <button disabled={busy} onClick={() => act('reject')}>
                  Reject
                </button>
              </div>
            </section>
          )}

          {task.status === 'blocked' && (
            <section className="panel">
              <h3>Blocked</h3>
              <p className="muted">Start a new agent session and retry with a clean slate.</p>
              <button disabled={busy} onClick={() => act('unblock')}>
                Unblock
              </button>
              <button className="ok" disabled={busy} onClick={() => act('new_session')}>
                New session &amp; retry
              </button>
            </section>
          )}

          {task.status === 'backlog' && (
            <section className="panel">
              <h3>Backlog — pending human approval</h3>
              <p className="muted">
                Approved tasks move to the queue and start execution. A task is not
                dispatched to the agent until a human approves it here.
              </p>
              <div className="row">
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" />
                <button className="ok" disabled={busy} onClick={() => act('approve_execution')}>
                  Approve for execution
                </button>
              </div>
            </section>
          )}

          {error && <ErrorBanner message={error} />}
        </div>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------- app
export default function App() {
  const { tasks, metrics, caps, harnessData, error, refresh } = useTaskStore()
  const [view, setView] = useState<'board' | 'new' | 'reviews' | 'settings'>('board')
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    setSelected(null)
  }, [view])

  const reviewCount = tasks.filter((t) => t.status === 'needs_review').length
  const adapter = caps[0]?.adapter ?? '…'

  return (
    <div className="app-root">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◧</span> TaskExec
        </div>
        <span className={`adapter-chip adapter-${adapter}`} title={`Agent execution adapter: ${adapter}`}>
          ⚙ {adapter}
        </span>
        <nav>
          <button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>
            Board
          </button>
          <button className={view === 'new' ? 'active' : ''} onClick={() => setView('new')}>
            New task
          </button>
          <button className={view === 'reviews' ? 'active' : ''} onClick={() => setView('reviews')}>
            Reviews {reviewCount > 0 ? <span className="badge">{reviewCount}</span> : null}
          </button>
          <button className={view === 'settings' ? 'active' : ''} onClick={() => setView('settings')}>
            Settings
          </button>
        </nav>
        {metrics && (
          <div className="stats">
            <span title="tasks">
              {metrics.by_status.done} done
            </span>
            <span title="queued + executing + verifying">
              {metrics.by_status.queued + metrics.by_status.executing + metrics.by_status.verifying} in flight
            </span>
            <span className={metrics.escalation_count ? 'warn' : ''} title="escaped to human review">
              {metrics.escalation_count} escalated
            </span>
          </div>
        )}
        <Checkout />
      </header>

      {error && <ErrorBanner message={`Backend unreachable: ${error}`} />}

      <main className="content">
        {view === 'board' ? (
          <Board tasks={tasks} onClick={setSelected} />
        ) : view === 'new' ? (
          <NewTaskForm tasks={tasks} caps={caps} harnessData={harnessData} refresh={refresh} onCreated={(id) => setSelected(id)} />
        ) : view === 'reviews' ? (
          <Reviews refresh={refresh} onOpen={setSelected} />
        ) : (
          <Settings />
        )}
      </main>

      {selected && <TaskDetail id={selected} refresh={refresh} onClose={() => setSelected(null)} />}
    </div>
  )
}