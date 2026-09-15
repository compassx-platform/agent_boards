import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "@/lib/routing";
import {
  AlertCircle,
  Cpu,
  ListChecks,
  Play,
  PlusCircle,
  RotateCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import type {
  CompassXApp,
  CompassXWorkspace,
  Criterion,
  HarnessesResponse,
  Priority,
  RiskTier,
  TaskCreateInput,
} from "@/board/lib/api";
import {
  DEFAULT_HARNESS,
  api,
} from "@/board/lib/api";
import { Button } from "@/components/ui/button";
import { PageScroll } from "@/components/PageScroll";

const CHECK_LABEL: Record<string, string> = {
  automated_test: "Automated test (shell command)",
  schema_check: "Schema check",
  output_match: "Output match (regex)",
  human_approval: "Human approval",
  manual_checklist: "Manual checklist",
}

const CHECK_HINT: Record<string, string> = {
  automated_test: '{"command": "grep -q success artifact.txt"}',
  schema_check: '{"required_keys": ["status"]}',
  output_match: '{"pattern": "success"}',
  human_approval: "{}",
  manual_checklist: "{}",
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

export function NewTaskPage() {
  const navigate = useNavigate()
  const [caps, setCaps] = useState<{ name: string; adapter: string }[]>([])
  const [harnessData, setHarnessData] = useState<HarnessesResponse | null>(null)
  const [title, setTitle] = useState("")
  const [intent, setIntent] = useState("")
  const [priority, setPriority] = useState<Priority>("normal")
  const [risk, setRisk] = useState<RiskTier>("low")
  const [capability, setCapability] = useState("default")
  const [harness, setHarness] = useState(DEFAULT_HARNESS)
  const [planRequired, setPlanRequired] = useState(false)
  const [bypassVerification, setBypassVerification] = useState(true)
  const [bypassOutcome, setBypassOutcome] = useState("needs_review")
  const [workspace, setWorkspace] = useState("")
  const [criteria, setCriteria] = useState<CriterionDraft[]>([
    {
      description: "Agent output indicates success",
      check_type: "output_match",
      check_config: '{"pattern": "success"}',
    },
  ])
  const [conversation, setConversation] = useState("")
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [apps, setApps] = useState<CompassXApp[]>([])
  const [appsError, setAppsError] = useState<string | null>(null)
  const [appId, setAppId] = useState("")
  const [reuseWorkspace, setReuseWorkspace] = useState(false)
  const [appWorkspaces, setAppWorkspaces] = useState<CompassXWorkspace[]>([])
  const [appWsId, setAppWsId] = useState("")

  useEffect(() => {
    Promise.all([api.capabilities(), api.harnesses()])
      .then(([c, h]) => {
        setCaps(c)
        setHarnessData(h)
        if (h.default) setHarness(h.default)
      })
      .catch(() => undefined)
  }, [])

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
    setAppWsId("")
    setAppWorkspaces([])
    if (appId && reuseWorkspace) {
      api
        .compassxWorkspaces(appId)
        .then((res) => setAppWorkspaces(res.workspaces ?? []))
        .catch((e) => setAppsError(String(e)))
    }
  }, [appId, reuseWorkspace])

  function applyParsed(p: Partial<TaskCreateInput>) {
    setTitle(p.title ?? "")
    setIntent(p.intent ?? "")
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
        depends_on: [],
        context: [],
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
              check_type: c.check_type as Criterion["check_type"],
              check_config: cfg,
            }
          }),
      }
      if (!payload.title) throw new Error("Title is required")
      if (!payload.criteria.length)
        throw new Error("At least one definition-of-done criterion is required")
      const task = await api.createTask(payload)
      navigate(`/board`)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <PageScroll contentClassName="px-6 py-6 max-w-4xl mx-auto w-full">
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">New Task</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Create an autonomous agent assignment with clear intent and definition of done.
          </p>
        </div>

        {/* AI Conversational Parsing Card */}
        <div className="bg-card border border-border/70 rounded-xl p-5 shadow-xs flex flex-col gap-3">
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
              className="flex-1 bg-background border border-input rounded-lg px-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-accent"
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
              {parsing ? "Parsing…" : "Parse Prompt"}
            </Button>
          </div>
        </div>

        {/* Main Task Form */}
        <form
          onSubmit={submit}
          className="bg-card border border-border/70 rounded-xl p-6 shadow-xs flex flex-col gap-5"
        >
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
                    {h.name === harnessData?.default ? " (default)" : ""}
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
                  {a.name} {a.git_branch ? `(${a.git_branch})` : ""}
                </option>
              ))}
            </select>
            {appsError && <p className="text-xs text-destructive">{appsError}</p>}
            {appId !== "" && (
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
                      description: "",
                      check_type: "output_match",
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
                  {c.check_type !== "human_approval" && c.check_type !== "manual_checklist" && (
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
              {saving ? "Creating Task…" : "Create & Queue Task"}
            </Button>
          </div>
        </form>
      </div>
    </PageScroll>
  )
}
