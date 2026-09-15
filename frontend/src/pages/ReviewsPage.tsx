import { useEffect, useState } from "react";
import { Link } from "@/lib/routing";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Inbox,
  RotateCw,
} from "lucide-react";
import type { Task } from "@/board/lib/api";
import { api } from "@/board/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageScroll } from "@/components/PageScroll";
import { cn } from "@/lib/utils";

function RiskBadge({ risk }: { risk: string }) {
  const variants: Record<string, string> = {
    high: "border-red-500/40 text-red-400 bg-red-500/10",
    medium: "border-amber-500/40 text-amber-400 bg-amber-500/10",
    low: "border-emerald-500/40 text-emerald-400 bg-emerald-500/10",
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

export function ReviewsPage() {
  const [items, setItems] = useState<Task[]>([])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = () => {
    void api.reviews().then(setItems).catch(() => undefined)
  }

  useEffect(() => {
    reload()
  }, [])

  async function act(id: string, action: "approve" | "retry" | "reject" | "approve_plan") {
    setBusy(id)
    setError(null)
    try {
      await api.review(id, action, notes[id] ?? "")
      setItems(items.filter((t) => t.id !== id))
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <PageScroll contentClassName="px-6 py-6 max-w-4xl mx-auto w-full">
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Review Queue</h1>
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
                  <Link
                    to={`/tasks/${t.id}`}
                    className="text-left font-semibold text-base text-foreground hover:text-primary transition-colors"
                  >
                    {t.title}
                  </Link>
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

              {t.plan_status === "awaiting_approval" ? (
                <div className="flex flex-col gap-2 p-3.5 bg-muted/40 border border-border/50 rounded-lg">
                  <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
                    Proposed Implementation Plan
                  </h4>
                  <pre className="text-xs font-mono bg-background p-3 rounded-md overflow-x-auto max-h-60 text-muted-foreground whitespace-pre-wrap">
                    {t.plan_text ?? "(Plan generated, click task to inspect details)"}
                  </pre>
                </div>
              ) : (
                <div className="flex flex-col gap-1.5 p-3 bg-muted/30 border border-border/40 rounded-lg">
                  {t.criteria.map((c) => (
                    <div key={c.id} className="flex items-center gap-2 text-xs">
                      <span
                        className={cn(
                          "font-bold font-mono",
                          c.result === "pass"
                            ? "text-emerald-400"
                            : c.result === "fail"
                              ? "text-red-400"
                              : "text-amber-400",
                        )}
                      >
                        {c.result ?? "pending"}
                      </span>
                      <span className="text-foreground">{c.description}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex flex-col sm:flex-row items-center gap-2 pt-2 border-t border-border/40">
                <input
                  value={notes[t.id] ?? ""}
                  onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })}
                  placeholder={
                    t.plan_status === "awaiting_approval"
                      ? "Feedback or instructions to agent (optional)"
                      : "Reviewer comment or instructions"
                  }
                  className="flex-1 w-full bg-background border border-input rounded-lg px-3 py-1.5 text-xs text-foreground focus:ring-1 focus:ring-accent"
                />
                <div className="flex items-center gap-2 shrink-0">
                  {t.plan_status === "awaiting_approval" ? (
                    <>
                      <Button
                        size="sm"
                        onClick={() => act(t.id, "approve_plan")}
                        disabled={busy === t.id}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5"
                      >
                        <Check className="size-3.5" /> Approve Plan → Implement
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => act(t.id, "retry")}
                        disabled={busy === t.id}
                        className="gap-1.5"
                      >
                        <RotateCw className="size-3.5" /> Re-plan
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => act(t.id, "reject")}
                        disabled={busy === t.id}
                      >
                        Reject
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="sm"
                        onClick={() => act(t.id, "approve")}
                        disabled={busy === t.id}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5"
                      >
                        <Check className="size-3.5" /> Approve
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => act(t.id, "retry")}
                        disabled={busy === t.id}
                        className="gap-1.5"
                      >
                        <RotateCw className="size-3.5" /> Retry with Note
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => act(t.id, "reject")}
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
    </PageScroll>
  )
}
