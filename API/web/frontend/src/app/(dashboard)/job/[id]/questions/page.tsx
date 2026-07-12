"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  Loader2Icon, DownloadIcon, SearchIcon,
  FilterIcon, ArrowUpDownIcon, GraduationCapIcon,
  CheckIcon, XIcon, ShieldCheckIcon, ShieldAlertIcon,
  AlertTriangleIcon, TableIcon, LibraryIcon,
  BrainCircuitIcon, RefreshCwIcon, ThumbsDownIcon, ThumbsUpIcon,
  PlusIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { BLOOM_LEVELS, BloomBadge } from "@/components/bloom/bloom-level-selector"
import { QuestionDetailSheet } from "@/components/question-detail-sheet"
import { QuestionDetailView } from "@/components/question/question-detail-view"
import { QuestionStem } from "@/components/question/question-stem"
import { QuestionStatusBadge } from "@/components/question/question-status-badge"
import { EmptyState } from "@/components/empty-state"
import { FeedbackDialog, FeedbackThumbs } from "@/components/question/question-feedback"
import {
  addQuestionsToBank,
  checkBankDuplicates,
  createBank,
  generateMoreQuestions,
  getJobFeedback,
  getJobQuestions,
  listBanks,
  regenerateFromFeedback,
  reviewQuestion,
  submitQuestionFeedback,
  downloadJobExport,
  type DuplicateCheckResponse,
  type AddToBankResponse,
  type FeedbackRating,
  type Question,
  type QuestionBank,
  type QuestionFeedback,
} from "@/lib/api"
import { cn } from "@/lib/utils"

// ── Types ──────────────────────────────────────────────────────────────────

type SortBy = "risk" | "score" | "newest" | "topic"
type ViewMode = "review" | "quiz"
type VerifiedFilter = "all" | "verified" | "symbolic" | "unverified"

interface Filters {
  search: string
  bloom: string
  topic: string
  verified: VerifiedFilter
  sortBy: SortBy
}

// ── Filter Bar ─────────────────────────────────────────────────────────────

function FilterBar({
  filters, onChange, topics,
}: {
  filters: Filters
  onChange: (f: Filters) => void
  topics: string[]
}) {
  const sortLabels: Record<SortBy, string> = {
    risk: "Cần xem",
    score: "Score",
    topic: "Topic",
    newest: "Mặc định",
  }
  const nextSort: Record<SortBy, SortBy> = {
    risk: "score",
    score: "topic",
    topic: "newest",
    newest: "risk",
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-background p-3">
      {/* Search + sort */}
      <div className="grid gap-2 lg:grid-cols-[1fr_auto_auto]">
        <div className="relative min-w-0">
          <SearchIcon className="size-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <Input
            placeholder="Tìm theo stem, đáp án, chủ đề, mã câu..."
            value={filters.search}
            onChange={(e) => onChange({ ...filters, search: e.target.value })}
            className="pl-9"
          />
        </div>
        <select
          value={filters.topic}
          onChange={(e) => onChange({ ...filters, topic: e.target.value })}
          className="hidden h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="all">Tất cả chủ đề</option>
          {topics.map((topic) => (
            <option key={topic} value={topic}>{topic}</option>
          ))}
        </select>
        <select
          value={filters.verified}
          onChange={(e) => onChange({ ...filters, verified: e.target.value as VerifiedFilter })}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="all">Verifier: tất cả</option>
          <option value="verified">Đã verify</option>
          <option value="symbolic">Symbolic</option>
          <option value="unverified">Chưa verify</option>
        </select>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={() => onChange({ ...filters, sortBy: nextSort[filters.sortBy] })}
          title="Đổi tiêu chí sắp xếp"
        >
          <ArrowUpDownIcon className="size-3.5 mr-1" />
          {sortLabels[filters.sortBy]}
        </Button>
      </div>

      {/* Bloom filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <FilterIcon className="size-3" /> Bloom:
        </span>
        <button
          type="button"
          onClick={() => onChange({ ...filters, bloom: "all" })}
          className={cn(
            "text-xs rounded-full px-2.5 py-1 border transition",
            filters.bloom === "all"
              ? "bg-primary text-primary-foreground border-primary"
              : "hover:bg-accent"
          )}
        >
          Tất cả
        </button>
        {BLOOM_LEVELS.filter((b) => b.id !== "mixed").map((b) => {
          const active = filters.bloom === b.label
          return (
            <button
              type="button"
              key={b.id}
              onClick={() => onChange({ ...filters, bloom: b.label })}
              className={cn(
                "text-xs rounded-full px-2.5 py-1 border transition flex items-center gap-1",
                active
                  ? `${b.bg} ${b.border} ${b.text} font-medium`
                  : "hover:bg-accent"
              )}
            >
              {b.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Quiz View ──────────────────────────────────────────────────────────────

function QuizView({
  questions, onReview, jobId,
}: {
  questions: Question[]
  onReview: (id: string, action: "approve" | "reject") => void
  jobId: string
}) {
  const [idx, setIdx] = React.useState(0)
  void onReview // not used in quiz mode (kept for potential future use)
  void jobId

  if (questions.length === 0) {
    return (
      <p className="text-muted-foreground text-center py-12 text-sm">
        Không có câu hỏi nào để làm bài.
      </p>
    )
  }

  // Bảo vệ khi danh sách thu gọn (filter): clamp idx về safe range trong render.
  const safeIdx = Math.min(idx, questions.length - 1)
  const q = questions[safeIdx]
  return (
    <div className="flex flex-col gap-4">
      {/* Stepper */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {questions.map((qq, i) => (
          <button
            key={qq.question_id}
            type="button"
            onClick={() => setIdx(i)}
            className={cn(
              "size-8 rounded-md text-xs font-medium transition border",
              i === safeIdx
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-card hover:bg-accent border-border"
            )}
          >
            {i + 1}
          </button>
        ))}
      </div>

      {/* Detail — key đảm bảo state quiz reset giữa các câu */}
      <div className="rounded-xl border bg-card p-5">
        <QuestionDetailView
          key={q.question_id}
          question={q}
          view="quiz"
          index={safeIdx}
        />
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <Button
          size="sm"
          variant="outline"
          disabled={safeIdx === 0}
          onClick={() => setIdx((i) => Math.max(0, i - 1))}
        >
          ← Câu trước
        </Button>
        <span className="text-sm text-muted-foreground">
          Câu {safeIdx + 1} / {questions.length}
        </span>
        <Button
          size="sm"
          disabled={safeIdx >= questions.length - 1}
          onClick={() =>
            setIdx((i) => Math.min(questions.length - 1, i + 1))
          }
        >
          Câu tiếp →
        </Button>
      </div>
    </div>
  )
}

// ── Card Grid ─────────────────────────────────────────────────────────────

function isSymbolicVerified(q: Question): boolean {
  const v = q.verification
  return v?.verified === true && !!v.engine && v.engine !== "none"
}

function isVerified(q: Question): boolean {
  return q.verification?.verified === true
}

function riskScore(q: Question): number {
  const quality = q.judging?.quality ?? 0
  const grounding = q.judging?.grounding ?? 0
  const bloom = q.judging?.bloom_alignment ?? 0
  return (
    (q.review_status === "needs_revision" ? 4 : 0) +
    (!isVerified(q) ? 2 : 0) +
    (quality < 0.75 ? 2 : 0) +
    (grounding < 0.8 ? 1 : 0) +
    (bloom < 0.75 ? 1 : 0)
  )
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`
}

function avg(values: Array<number | undefined | null>): number | null {
  const nums = values.filter((v): v is number => typeof v === "number" && !Number.isNaN(v))
  return nums.length ? nums.reduce((sum, value) => sum + value, 0) / nums.length : null
}

function BankMetric({
  label, value, sub, tone = "default",
}: {
  label: string
  value: string | number
  sub?: string
  tone?: "default" | "good" | "warn" | "bad"
}) {
  const toneClass = {
    default: "border-border bg-background",
    good: "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100",
    warn: "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100",
    bad: "border-rose-200 bg-rose-50 text-rose-950 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-100",
  }[tone]

  return (
    <div className={cn("rounded-lg border p-3", toneClass)}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

function QuestionBankSummary({
  questions, rejected, approved, pending, needsRevision,
}: {
  questions: Question[]
  rejected: Question[]
  approved: Question[]
  pending: Question[]
  needsRevision: Question[]
}) {
  const attempted = questions.length + rejected.length
  const avgQuality = avg(questions.map((q) => q.judging?.quality))
  const lowRisk = questions.filter((q) => riskScore(q) >= 4).length

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
      <BankMetric label="Accepted" value={questions.length} sub={attempted ? pct(questions.length / attempted) : "0%"} tone="good" />
      <BankMetric label="Queue" value={pending.length + needsRevision.length} sub={`${needsRevision.length} cần sửa`} tone={needsRevision.length ? "warn" : "default"} />
      <BankMetric label="Approved" value={approved.length} sub={questions.length ? pct(approved.length / questions.length) : "0%"} />
      <BankMetric label="Rejected" value={rejected.length} sub={attempted ? pct(rejected.length / attempted) : "0%"} tone={rejected.length ? "bad" : "default"} />
      <BankMetric label="Quality" value={avgQuality == null ? "n/a" : avgQuality.toFixed(2)} sub="average" tone={avgQuality != null && avgQuality < 0.75 ? "warn" : "default"} />
      <BankMetric label="Risk" value={lowRisk} sub="cần xem kỹ" tone={lowRisk ? "warn" : "default"} />
    </div>
  )
}

function OutcomeBadges({ codes }: { codes?: string[] }) {
  if (!codes || codes.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map((code) => (
        <Badge
          key={code}
          variant="outline"
          className="border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-300"
        >
          {code}
        </Badge>
      ))}
    </div>
  )
}

function FeedbackBar({
  upCount, downCount, total, regenLoading, regenError, onRegenerate,
}: {
  upCount: number
  downCount: number
  total: number
  regenLoading: boolean
  regenError: string
  onRegenerate: () => void
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-violet-200 bg-violet-50/50 p-3 dark:border-violet-900 dark:bg-violet-950/20 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-2.5">
        <BrainCircuitIcon className="mt-0.5 size-5 shrink-0 text-violet-600 dark:text-violet-400" />
        <div>
          <p className="text-sm font-medium">
            Học từ phản hồi của bạn (RLHF)
            <span className="ml-2 inline-flex items-center gap-2 text-xs font-normal text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <ThumbsUpIcon className="size-3 text-emerald-600" />{upCount}
              </span>
              <span className="inline-flex items-center gap-1">
                <ThumbsDownIcon className="size-3 text-rose-600" />{downCount}
              </span>
              <span>/ {total} câu</span>
            </span>
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Đánh giá 👍/👎 từng câu (kèm lý do). Khi sinh lại: câu 👎 được thay bằng câu mới
            theo đúng ý bạn, câu còn lại giữ nguyên.
          </p>
          {regenError && <p className="mt-1 text-xs text-destructive">{regenError}</p>}
        </div>
      </div>
      <Button
        size="sm"
        disabled={downCount === 0 || regenLoading}
        onClick={onRegenerate}
        className="shrink-0 bg-violet-600 text-white hover:bg-violet-700 disabled:bg-muted disabled:text-muted-foreground"
        title={downCount === 0 ? "Chê (👎) ít nhất một câu để sinh lại" : undefined}
      >
        {regenLoading
          ? <Loader2Icon className="mr-1.5 size-3.5 animate-spin" />
          : <RefreshCwIcon className="mr-1.5 size-3.5" />}
        Sinh lại {downCount > 0 ? `${downCount} câu ` : ""}theo phản hồi
      </Button>
    </div>
  )
}

function VerifierMini({ q }: { q: Question }) {
  if (isSymbolicVerified(q)) {
    return <Badge variant="outline" className="border-emerald-300 text-emerald-700"><ShieldCheckIcon className="mr-1 size-3" />{q.verification?.engine}</Badge>
  }
  if (isVerified(q)) {
    return <Badge variant="outline" className="border-emerald-300 text-emerald-700"><ShieldCheckIcon className="mr-1 size-3" />verified</Badge>
  }
  return <Badge variant="outline" className="text-amber-700"><ShieldAlertIcon className="mr-1 size-3" />none</Badge>
}

function QuestionBankTable({
  items, empty, onItemClick, onReview, rejectedTable = false,
  feedbackMap, onFeedback,
}: {
  items: Question[]
  empty: string
  onItemClick: (q: Question) => void
  onReview?: (id: string, action: "approve" | "reject") => void
  rejectedTable?: boolean
  feedbackMap?: Record<string, QuestionFeedback>
  onFeedback?: (q: Question, rating: FeedbackRating) => void
}) {
  if (items.length === 0) {
    return (
      <p className="text-muted-foreground py-12 text-center text-sm">{empty}</p>
    )
  }
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="bg-muted/60 text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="w-14 px-3 py-2 text-left font-medium">#</th>
              <th className="w-28 px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-left font-medium">Question</th>
              <th className="w-44 px-3 py-2 text-left font-medium">Topic</th>
              <th className="w-32 px-3 py-2 text-left font-medium">Bloom</th>
              <th className="w-28 px-3 py-2 text-left font-medium">Chuẩn ĐR</th>
              {!rejectedTable && onFeedback && (
                <th className="w-24 px-3 py-2 text-left font-medium">Phản hồi</th>
              )}
              <th className="hidden w-32 px-3 py-2 text-left font-medium">Verify</th>
              <th className="w-24 px-3 py-2 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
      {items.map((q, idx) => (
            <tr
              key={q.question_id ?? q.blueprint_slot_id ?? `q-${idx}`}
              className={cn(
                "border-b last:border-b-0 hover:bg-muted/40",
                q.stem ? "cursor-pointer" : "cursor-default"
              )}
              onClick={() => q.stem && onItemClick(q)}
            >
              <td className="px-3 py-3 font-mono text-xs text-muted-foreground">{idx + 1}</td>
              <td className="px-3 py-3">
                {rejectedTable ? (
                  <Badge variant="outline" className="border-rose-300 text-rose-700">
                    <AlertTriangleIcon className="mr-1 size-3" />
                    Rejected
                  </Badge>
                ) : (
                  <QuestionStatusBadge status={q.review_status} />
                )}
              </td>
              <td className="px-3 py-3">
                {q.stem ? (
                  <QuestionStem stem={q.stem} compact truncated className="text-foreground" />
                ) : (
                  <p className="line-clamp-2 text-sm text-muted-foreground">
                    {(q as Question & { reject_reason?: string }).reject_reason ?? "Không sinh được câu hỏi cho slot này."}
                  </p>
                )}
                <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span>{q.question_id ?? q.blueprint_slot_id}</span>
                  {riskScore(q) >= 4 && !rejectedTable && (
                    <span className="inline-flex items-center gap-1 text-amber-700">
                      <AlertTriangleIcon className="size-3" />
                      cần xem kỹ
                    </span>
                  )}
                </div>
              </td>
              <td className="px-3 py-3 text-xs text-muted-foreground">
                <span className="line-clamp-2">{q.topic ?? (q as Question & { doc_id?: string }).doc_id ?? "unknown"}</span>
              </td>
              <td className="px-3 py-3">
                {q.cognitive_level ? <BloomBadge level={q.cognitive_level} /> : <span className="text-xs text-muted-foreground">n/a</span>}
              </td>
              <td className="px-3 py-3"><OutcomeBadges codes={q.learning_outcomes} /></td>
              {!rejectedTable && onFeedback && (
                <td className="px-3 py-3">
                  {q.question_id ? (
                    <FeedbackThumbs
                      feedback={feedbackMap?.[q.question_id]}
                      onOpen={(rating) => onFeedback(q, rating)}
                    />
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
              )}
              <td className="hidden px-3 py-3"><VerifierMini q={q} /></td>
              <td className="px-3 py-3">
                {onReview && q.question_id && !rejectedTable && (
                  <div className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      className="size-8 p-0 text-emerald-700"
                      title="Duyệt"
                      onClick={(e) => {
                        e.stopPropagation()
                        onReview(q.question_id, "approve")
                      }}
                    >
                      <CheckIcon className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="size-8 p-0 text-rose-700"
                      title="Từ chối"
                      onClick={(e) => {
                        e.stopPropagation()
                        onReview(q.question_id, "reject")
                      }}
                    >
                      <XIcon className="size-4" />
                    </Button>
                  </div>
                )}
              </td>
            </tr>
      ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function GenerateMoreDialog({
  open, onOpenChange, jobId, currentCount, hasFeedback, onStarted,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  jobId: string
  currentCount: number
  hasFeedback: boolean
  onStarted: () => void
}) {
  const [count, setCount] = React.useState(5)
  const [starting, setStarting] = React.useState(false)
  const [error, setError] = React.useState("")

  const handleStart = async () => {
    setStarting(true)
    setError("")
    try {
      await generateMoreQuestions(jobId, count)
      onStarted()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không sinh thêm được câu hỏi.")
      setStarting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Sinh thêm câu hỏi</DialogTitle>
          <DialogDescription>
            Tạo thêm câu hỏi mới từ cùng file PDF. {currentCount} câu hiện có được giữ
            nguyên, câu mới không lặp lại câu cũ
            {hasFeedback ? " và tuân theo phản hồi 👍/👎 bạn đã đánh giá" : ""}.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium">Số câu sinh thêm</span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
              className="h-9 w-20 rounded-md border bg-background px-3 text-center text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex gap-1.5">
              {[3, 5, 10].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setCount(n)}
                  className={cn(
                    "h-9 rounded-md border px-3 text-sm transition",
                    count === n
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background hover:bg-accent"
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" disabled={starting} onClick={() => onOpenChange(false)}>
            Huỷ
          </Button>
          <Button disabled={starting} onClick={handleStart}>
            {starting
              ? <Loader2Icon className="mr-2 size-4 animate-spin" />
              : <PlusIcon className="mr-2 size-4" />}
            Sinh thêm {count} câu
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const DUPLICATE_REASON_LABELS: Record<string, string> = {
  exact_stem: "Trùng nguyên văn",
  near_stem: "Đề bài gần giống",
  same_answer_similar_stem: "Cùng đáp án, đề tương tự",
  same_source_pages: "Cùng trang nguồn",
  semantic: "Trùng ý nghĩa",
}

function duplicateReasonLabel(type: string): string {
  return DUPLICATE_REASON_LABELS[type] ?? type
}

function AddToBankDialog({
  open, onOpenChange, questions, jobId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  questions: Question[]
  jobId: string
}) {
  const [banks, setBanks] = React.useState<QuestionBank[]>([])
  const [bankId, setBankId] = React.useState("")
  const [newBankName, setNewBankName] = React.useState("")
  const [duplicateAction, setDuplicateAction] = React.useState<"skip" | "replace" | "force">("skip")
  const [checking, setChecking] = React.useState(false)
  const [adding, setAdding] = React.useState(false)
  const [checkResult, setCheckResult] = React.useState<DuplicateCheckResponse | null>(null)
  const [addResult, setAddResult] = React.useState<AddToBankResponse | null>(null)
  const [message, setMessage] = React.useState("")
  const [error, setError] = React.useState("")

  React.useEffect(() => {
    if (!open) return
    listBanks()
      .then((data) => {
        const next = data.banks ?? []
        setBanks(next)
        setBankId((current) => current || next[0]?.bank_id || "")
      })
      .catch((err: Error) => setError(err.message))
  }, [open])

  const resolveBank = async (): Promise<string> => {
    if (newBankName.trim()) {
      const { bank } = await createBank(newBankName.trim())
      setBanks((prev) => [bank, ...prev])
      setBankId(bank.bank_id)
      setNewBankName("")
      return bank.bank_id
    }
    return bankId
  }

  const handleCheck = async () => {
    setChecking(true)
    setError("")
    setMessage("")
    setAddResult(null)
    try {
      const targetBankId = await resolveBank()
      if (!targetBankId) throw new Error("Chọn hoặc tạo một ngân hàng trước.")
      const result = await checkBankDuplicates(targetBankId, questions)
      setCheckResult(result)
      const duplicateCount = result.results.filter((item) => item.duplicates.length > 0).length
      setMessage(
        duplicateCount > 0
          ? `Phát hiện ${duplicateCount}/${questions.length} câu có khả năng trùng với ngân hàng (chi tiết bên dưới).`
          : `Không phát hiện câu trùng — ${questions.length} câu đều mới so với ngân hàng.`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kiểm tra trùng thất bại")
    } finally {
      setChecking(false)
    }
  }

  const handleAdd = async () => {
    setAdding(true)
    setError("")
    try {
      const targetBankId = await resolveBank()
      if (!targetBankId) throw new Error("Chọn hoặc tạo một ngân hàng trước.")
      const result = await addQuestionsToBank(targetBankId, {
        questions,
        sourceJobId: jobId,
        duplicateAction,
      })
      const parts = [`Đã thêm ${result.added.length} câu`]
      if (result.skipped.length > 0) parts.push(`bỏ qua ${result.skipped.length} câu trùng`)
      if (result.replaced.length > 0) parts.push(`thay thế ${result.replaced.length} câu cũ`)
      setMessage(parts.join(", ") + ".")
      setAddResult(result)
      setCheckResult(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Thêm vào ngân hàng thất bại")
    } finally {
      setAdding(false)
    }
  }

  const duplicateCount = checkResult?.results.filter((item) => item.duplicates.length > 0).length ?? 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Thêm vào ngân hàng câu hỏi</DialogTitle>
          <DialogDescription>{questions.length} câu đã chấp nhận sẽ được thêm.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">Ngân hàng có sẵn</span>
              <select
                value={bankId}
                onChange={(event) => setBankId(event.target.value)}
                className="h-9 rounded-md border bg-background px-3 text-sm"
              >
                <option value="">Chọn ngân hàng</option>
                {banks.map((bank) => (
                  <option key={bank.bank_id} value={bank.bank_id}>{bank.name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">Hoặc tạo mới</span>
              <Input value={newBankName} onChange={(event) => setNewBankName(event.target.value)} placeholder="Tên ngân hàng mới" />
            </label>
          </div>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted-foreground">Khi gặp câu trùng</span>
            <select
              value={duplicateAction}
              onChange={(event) => setDuplicateAction(event.target.value as "skip" | "replace" | "force")}
              className="h-9 rounded-md border bg-background px-3 text-sm"
            >
              <option value="skip">Bỏ qua câu trùng (khuyên dùng)</option>
              <option value="replace">Thay câu cũ bằng câu mới</option>
              <option value="force">Vẫn thêm dù trùng</option>
            </select>
          </label>

          {message && (
            <p className={cn(
              "rounded-md border px-3 py-2 text-sm",
              addResult
                ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
                : "text-muted-foreground",
            )}>
              {message}
            </p>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {(checkResult ?? addResult) && !(checkResult ?? addResult)!.semantic_enabled && (
            <p className="text-xs text-amber-700 dark:text-amber-500">
              Chưa bật so trùng theo ý nghĩa (cần GEMINI_API_KEY trong .env) — hiện chỉ so trùng
              theo văn bản nên câu diễn đạt khác đi có thể lọt.
            </p>
          )}
          {checkResult && duplicateCount > 0 && (
            <div className="max-h-56 overflow-auto rounded-md border">
              {checkResult.results.filter((item) => item.duplicates.length > 0).slice(0, 8).map((item) => (
                <div key={item.question_id ?? item.stem} className="border-b p-3 last:border-b-0">
                  <p className="line-clamp-2 text-sm">{item.stem}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {item.duplicates[0]?.reasons.map((reason) => (
                      <Badge key={`${reason.type}-${reason.score}`} variant="outline">
                        {duplicateReasonLabel(reason.type)} {Math.round(reason.score * 100)}%
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {addResult && addResult.skipped.length > 0 && (
            <div className="max-h-56 overflow-auto rounded-md border">
              <p className="border-b bg-muted/60 px-3 py-2 text-xs font-medium text-muted-foreground">
                Các câu bị bỏ qua vì trùng với câu đã có trong ngân hàng:
              </p>
              {addResult.skipped.slice(0, 8).map((item, idx) => (
                <div key={item.question_id ?? `skip-${idx}`} className="border-b p-3 last:border-b-0">
                  <p className="line-clamp-2 text-sm">{item.stem}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {item.duplicates[0]?.reasons.map((reason) => (
                      <Badge key={`${reason.type}-${reason.score}`} variant="outline" className="border-amber-300 text-amber-700 dark:text-amber-500">
                        {duplicateReasonLabel(reason.type)} {Math.round(reason.score * 100)}%
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCheck} disabled={checking || adding || questions.length === 0}>
            {checking && <Loader2Icon className="mr-2 size-4 animate-spin" />}
            Kiểm tra trùng trước
          </Button>
          <Button onClick={handleAdd} disabled={checking || adding || questions.length === 0}>
            {adding && <Loader2Icon className="mr-2 size-4 animate-spin" />}
            {adding ? "Đang thêm..." : "Thêm vào ngân hàng"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function QuestionsPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [questions, setQuestions] = React.useState<Question[]>([])
  const [rejected, setRejected] = React.useState<Question[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState("")

  const [selected, setSelected] = React.useState<Question | null>(null)
  const [sheetOpen, setSheetOpen] = React.useState(false)
  const [bankDialogOpen, setBankDialogOpen] = React.useState(false)
  const [moreDialogOpen, setMoreDialogOpen] = React.useState(false)

  // ── Feedback (RLHF) state ──
  const [feedbackMap, setFeedbackMap] = React.useState<Record<string, QuestionFeedback>>({})
  const [fbTarget, setFbTarget] = React.useState<Question | null>(null)
  const [fbRating, setFbRating] = React.useState<FeedbackRating>("up")
  const [fbOpen, setFbOpen] = React.useState(false)
  const [fbSaving, setFbSaving] = React.useState(false)
  const [regenLoading, setRegenLoading] = React.useState(false)
  const [regenError, setRegenError] = React.useState("")

  const [filters, setFilters] = React.useState<Filters>({
    search: "",
    bloom: "all",
    topic: "all",
    verified: "all",
    sortBy: "risk",
  })

  const [viewMode, setViewMode] = React.useState<ViewMode>("review")

  React.useEffect(() => {
    getJobQuestions(id)
      .then((data) => {
        setQuestions(data.questions ?? [])
        setRejected(data.rejected ?? [])
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
    // Feedback là phụ trợ — lỗi tải không chặn trang.
    getJobFeedback(id)
      .then((data) => {
        const map: Record<string, QuestionFeedback> = {}
        for (const fb of data.feedback ?? []) map[fb.question_id] = fb
        setFeedbackMap(map)
      })
      .catch(() => {})
  }, [id])

  const openFeedback = (q: Question, rating: FeedbackRating) => {
    setFbTarget(q)
    setFbRating(rating)
    setFbOpen(true)
  }

  const handleFeedbackSave = async (payload: {
    rating: FeedbackRating
    tags: string[]
    comment: string
  }) => {
    if (!fbTarget) return
    setFbSaving(true)
    try {
      await submitQuestionFeedback(id, { question_id: fbTarget.question_id, ...payload })
      setFeedbackMap((prev) => ({
        ...prev,
        [fbTarget.question_id]: { question_id: fbTarget.question_id, ...payload },
      }))
      setFbOpen(false)
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Lưu phản hồi thất bại.")
    } finally {
      setFbSaving(false)
    }
  }

  const handleFeedbackClear = async () => {
    if (!fbTarget) return
    setFbSaving(true)
    try {
      await submitQuestionFeedback(id, { question_id: fbTarget.question_id, rating: null })
      setFeedbackMap((prev) => {
        const next = { ...prev }
        delete next[fbTarget.question_id]
        return next
      })
      setFbOpen(false)
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Xoá phản hồi thất bại.")
    } finally {
      setFbSaving(false)
    }
  }

  const handleRegenerate = async () => {
    setRegenLoading(true)
    setRegenError("")
    try {
      await regenerateFromFeedback(id)
      router.push(`/job/${id}/generate`)
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Không sinh lại được theo phản hồi.")
      setRegenLoading(false)
    }
  }

  const handleReview = async (questionId: string, action: "approve" | "reject") => {
    await reviewQuestion(id, questionId, action)
    setQuestions((prev) =>
      prev.map((q) =>
        q.question_id === questionId
          ? { ...q, review_status: action === "approve" ? "approved" : "rejected" }
          : q
      )
    )
    setSelected((s) =>
      s && s.question_id === questionId
        ? { ...s, review_status: action === "approve" ? "approved" : "rejected" }
        : s
    )
  }

  const openDetail = (q: Question) => {
    setSelected(q)
    setSheetOpen(true)
  }

  // Filters + sort
  const filterFn = React.useCallback(
    (q: Question) => {
      if (filters.bloom !== "all" && q.cognitive_level !== filters.bloom) return false
      if (filters.topic !== "all" && q.topic !== filters.topic) return false
      if (filters.verified === "verified" && !isVerified(q)) return false
      if (filters.verified === "symbolic" && !isSymbolicVerified(q)) return false
      if (filters.verified === "unverified" && isVerified(q)) return false
      if (filters.search) {
        const needle = filters.search.toLowerCase()
        const opts = Array.isArray(q.options) ? q.options : []
        const haystack = [
          q.question_id ?? "",
          q.blueprint_slot_id ?? "",
          q.stem ?? "",
          q.topic ?? "",
          (q as Question & { reject_reason?: string }).reject_reason ?? "",
          ...opts.map((o) => o.text),
        ]
          .join(" ")
          .toLowerCase()
        if (!haystack.includes(needle)) return false
      }
      return true
    },
    [filters]
  )

  const sortFn = React.useCallback(
    (a: Question, b: Question) => {
      if (filters.sortBy === "risk") {
        return riskScore(b) - riskScore(a)
      }
      if (filters.sortBy === "score") {
        return (b.judging?.quality ?? 0) - (a.judging?.quality ?? 0)
      }
      if (filters.sortBy === "topic") {
        return (a.topic ?? "").localeCompare(b.topic ?? "")
      }
      return 0
    },
    [filters.sortBy]
  )

  const filteredAccepted = React.useMemo(
    () => questions.filter(filterFn).sort(sortFn),
    [questions, filterFn, sortFn]
  )
  const filteredRejected = React.useMemo(
    () => rejected.filter(filterFn).sort(sortFn),
    [rejected, filterFn, sortFn]
  )

  const allApproved = questions.filter((q) => q.review_status === "approved")
  const allNeedsRevision = questions.filter((q) => q.review_status === "needs_revision")
  const allPending = questions.filter((q) => q.review_status === "pending_review")

  const approved = filteredAccepted.filter((q) => q.review_status === "approved")
  const needsRevision = filteredAccepted.filter((q) => q.review_status === "needs_revision")
  const pending = filteredAccepted.filter((q) => q.review_status === "pending_review")
  const reviewQueue = [...needsRevision, ...pending]

  const bloomCounts = React.useMemo(() => {
    const map: Record<string, number> = {}
    questions.forEach((q) => {
      const k = q.cognitive_level ?? "unknown"
      map[k] = (map[k] || 0) + 1
    })
    return map
  }, [questions])

  const topics = React.useMemo(() => {
    const set = new Set<string>()
    questions.forEach((q) => q.topic && set.add(q.topic))
    rejected.forEach((q) => q.topic && set.add(q.topic))
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [questions, rejected])

  // Quiz mode dùng các câu đã approved (hoặc tất cả nếu chưa approve cái nào)
  const quizPool = React.useMemo(() => {
    const approvedList = filteredAccepted.filter(
      (q) => q.review_status === "approved"
    )
    return approvedList.length > 0 ? approvedList : filteredAccepted
  }, [filteredAccepted])

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Loader2Icon className="size-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Câu hỏi sinh ra</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            <code className="text-xs bg-muted px-1 rounded">{id}</code>
            {" — "}
            <span className="text-emerald-600 font-medium">{questions.length}</span> chấp nhận ·{" "}
            <span className="text-rose-600 font-medium">{rejected.length}</span> từ chối ·{" "}
            <span className="text-foreground font-medium">{allApproved.length}</span> đã duyệt
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* View mode toggle */}
          <div className="flex rounded-lg border p-0.5 bg-muted">
            <button
              type="button"
              onClick={() => setViewMode("review")}
              className={cn(
                "flex items-center gap-1 rounded px-3 py-1 text-xs font-medium transition",
                viewMode === "review"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <TableIcon className="size-3.5" />
              Duyệt
            </button>
            <button
              type="button"
              onClick={() => setViewMode("quiz")}
              className={cn(
                "flex items-center gap-1 rounded px-3 py-1 text-xs font-medium transition",
                viewMode === "quiz"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <GraduationCapIcon className="size-3.5" />
              Làm bài
            </button>
          </div>

          <Button
            variant="outline"
            onClick={() => setMoreDialogOpen(true)}
            disabled={questions.length === 0}
            title="Tạo thêm câu hỏi mới từ cùng PDF, giữ nguyên câu hiện có"
          >
            <PlusIcon className="size-4" />
            Sinh thêm
          </Button>

          <Button
            variant="outline"
            onClick={() => setBankDialogOpen(true)}
            disabled={questions.length === 0}
          >
            <LibraryIcon className="size-4" />
            Thêm vào ngân hàng
          </Button>

          <button
            type="button"
            onClick={() => downloadJobExport(id)}
            className="inline-flex items-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium shadow-sm hover:bg-accent shrink-0"
          >
            <DownloadIcon className="size-4" />
            Xuất JSON
          </button>
        </div>
      </div>

      {/* Stats per Bloom */}
      {Object.keys(bloomCounts).length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {BLOOM_LEVELS.filter((b) => b.id !== "mixed").map((b) => {
            const count = bloomCounts[b.label] ?? 0
            if (count === 0) return null
            return (
              <span
                key={b.id}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs",
                  b.bg, b.border, b.text
                )}
              >
                <span className="font-bold">{count}</span> {b.label}
              </span>
            )
          })}
        </div>
      )}

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {(questions.length > 0 || rejected.length > 0) && (
        <QuestionBankSummary
          questions={questions}
          rejected={rejected}
          approved={allApproved}
          pending={allPending}
          needsRevision={allNeedsRevision}
        />
      )}

      {questions.length === 0 && rejected.length === 0 && !error && (
        <EmptyState variant="questions" />
      )}

      {(questions.length > 0 || rejected.length > 0) && (
        <>
          {viewMode === "review" ? (
            <>
              {questions.length > 0 && (
                <FeedbackBar
                  upCount={questions.filter((q) => feedbackMap[q.question_id]?.rating === "up").length}
                  downCount={questions.filter((q) => feedbackMap[q.question_id]?.rating === "down").length}
                  total={questions.length}
                  regenLoading={regenLoading}
                  regenError={regenError}
                  onRegenerate={handleRegenerate}
                />
              )}
              <FilterBar
                filters={filters}
                onChange={setFilters}
                topics={topics}
              />

              <Tabs defaultValue="queue">
                <TabsList>
                  <TabsTrigger value="queue">
                    Cần duyệt ({reviewQueue.length})
                  </TabsTrigger>
                  <TabsTrigger value="all">
                    Accepted ({filteredAccepted.length})
                  </TabsTrigger>
                  <TabsTrigger value="approved">
                    Đã duyệt ({approved.length})
                  </TabsTrigger>
                  <TabsTrigger value="rejected">
                    Từ chối ({filteredRejected.length})
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="queue" className="mt-4">
                  <QuestionBankTable
                    items={reviewQueue}
                    empty="Không có câu nào cần duyệt với filter hiện tại."
                    onItemClick={openDetail}
                    onReview={handleReview}
                    feedbackMap={feedbackMap}
                    onFeedback={openFeedback}
                  />
                </TabsContent>
                <TabsContent value="all" className="mt-4">
                  <QuestionBankTable
                    items={filteredAccepted}
                    empty="Không có câu accepted nào với filter hiện tại."
                    onItemClick={openDetail}
                    onReview={handleReview}
                    feedbackMap={feedbackMap}
                    onFeedback={openFeedback}
                  />
                </TabsContent>
                <TabsContent value="approved" className="mt-4">
                  <QuestionBankTable
                    items={approved}
                    empty="Chưa duyệt câu nào với filter hiện tại."
                    onItemClick={openDetail}
                    feedbackMap={feedbackMap}
                    onFeedback={openFeedback}
                  />
                </TabsContent>
                <TabsContent value="rejected" className="mt-4">
                  <QuestionBankTable
                    items={filteredRejected}
                    empty="Không có câu bị từ chối với filter hiện tại."
                    onItemClick={openDetail}
                    rejectedTable
                  />
                </TabsContent>
              </Tabs>
            </>
          ) : (
            <QuizView
              questions={quizPool}
              onReview={handleReview}
              jobId={id}
            />
          )}
        </>
      )}

      {/* Detail Sheet (review mode) */}
      <QuestionDetailSheet
        question={selected}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onReview={handleReview}
      />
      <AddToBankDialog
        open={bankDialogOpen}
        onOpenChange={setBankDialogOpen}
        questions={questions}
        jobId={id}
      />
      <GenerateMoreDialog
        open={moreDialogOpen}
        onOpenChange={setMoreDialogOpen}
        jobId={id}
        currentCount={questions.length}
        hasFeedback={Object.keys(feedbackMap).length > 0}
        onStarted={() => router.push(`/job/${id}/generate`)}
      />
      <FeedbackDialog
        open={fbOpen}
        onOpenChange={setFbOpen}
        question={fbTarget}
        initialRating={fbRating}
        existing={fbTarget ? feedbackMap[fbTarget.question_id] : undefined}
        saving={fbSaving}
        onSave={handleFeedbackSave}
        onClear={handleFeedbackClear}
      />
    </div>
  )
}
