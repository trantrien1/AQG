"use client"

import * as React from "react"
import {
  ShieldCheckIcon, ShieldXIcon, AlertTriangleIcon,
  StarIcon, FileTextIcon, BookOpenIcon, GraduationCapIcon,
  EyeIcon, RotateCcwIcon, CheckCircle2Icon, XCircleIcon,
  TargetIcon,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BloomBadge } from "@/components/bloom/bloom-level-selector"
import { MathContent } from "@/components/math-content"
import { QuestionStem } from "./question-stem"
import { QuestionOptions, type OptionMode } from "./question-options"
import { QuestionTypeBadge } from "./question-type-badge"
import { QuestionStatusBadge } from "./question-status-badge"
import { ScorePill } from "./score-pill"
import { cn } from "@/lib/utils"
import {
  STATUS_BADGE_CLASS, STATUS_HELP, STATUS_LABEL, verificationStatus,
} from "@/lib/verification"
import type { Question } from "@/lib/api"

const TRAIT_LABELS: Record<string, string> = {
  clarity: "Rõ ràng",
  cognitive_depth: "Chiều sâu tư duy",
  bloom_alignment: "Bloom alignment",
  distractor_plausibility: "Distractor hợp lý",
  answer_uniqueness: "Đáp án duy nhất",
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    score >= 0.8
      ? "bg-emerald-500"
      : score >= 0.6
      ? "bg-amber-500"
      : "bg-rose-500"
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full transition-all", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono w-10 text-right text-muted-foreground">
        {score.toFixed(2)}
      </span>
    </div>
  )
}

/**
 * Nhãn kiểm chứng.
 *
 * Chỉ trạng thái `independently_verified` được hiển thị như một xác nhận mạnh.
 * `consistency_confirmed` nói rõ đây mới là sự nhất quán nội bộ, còn câu khái
 * niệm hiện "Không kiểm được bằng máy" chứ không được để trống cho người dùng
 * tự suy ra là đã kiểm.
 */
function VerifierBadge({ q }: { q: Question }) {
  const status = verificationStatus(q)
  const engine = q.verification?.engine ?? "none"
  const label = STATUS_LABEL[status]
  const title = STATUS_HELP[status]
  const suffix = engine && engine !== "none" ? ` · ${engine}` : ""

  if (status === "independently_verified") {
    return (
      <Badge
        title={title}
        className="bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800"
      >
        <ShieldCheckIcon className="size-3 mr-1" />
        {label}{suffix}
      </Badge>
    )
  }
  if (status === "consistency_confirmed") {
    return (
      <Badge variant="outline" title={title} className={STATUS_BADGE_CLASS[status]}>
        <ShieldCheckIcon className="size-3 mr-1" />
        {label}{suffix}
      </Badge>
    )
  }
  if (status === "refuted") {
    return (
      <Badge variant="destructive" title={title}>
        <ShieldXIcon className="size-3 mr-1" />
        {label}
      </Badge>
    )
  }
  return (
    <Badge variant="outline" title={title} className={STATUS_BADGE_CLASS[status]}>
      <AlertTriangleIcon className="size-3 mr-1" />
      {label}
    </Badge>
  )
}

interface QuestionDetailViewProps {
  question: Question
  /** review = chế độ giáo viên xem & duyệt; quiz = chế độ học sinh làm bài */
  view?: "review" | "quiz"
  className?: string
  /** index hiển thị #N */
  index?: number
}

/**
 * View chi tiết một câu hỏi.
 *
 * Có 2 chế độ:
 * - review: hiện đáp án đúng + reasoning + critic rubric + grounding (cho duyệt).
 * - quiz: ẩn đáp án đúng cho đến khi user submit; trải nghiệm "làm bài" thật.
 */
export function QuestionDetailView({
  question: q,
  view = "review",
  className,
  index,
}: QuestionDetailViewProps) {
  const options = Array.isArray(q.options) ? q.options : []
  const traits = q.judging?.quality_traits ?? {}
  const explanationsPerD = q.explanation_per_distractor ?? {}
  const detailedSteps = q.detailed_solution?.steps ?? []
  const detailedFinalAnswer = q.detailed_solution?.final_answer
  const hasDetailedSolution = detailedSteps.length > 0 || Boolean(detailedFinalAnswer)
  const whyOthersWrong = Array.isArray(q.why_others_wrong) ? q.why_others_wrong : []

  // Quiz mode state.
  // Caller chịu trách nhiệm reset state khi câu hỏi thay đổi bằng cách
  // truyền `key={question.question_id}` lên component này → React tự
  // unmount/mount lại, useState reset về initial.
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null)
  const [submitted, setSubmitted] = React.useState(false)
  const [showAnswerInQuiz, setShowAnswerInQuiz] = React.useState(false)

  let optionMode: OptionMode
  if (view === "quiz") {
    optionMode = submitted || showAnswerInQuiz ? "quiz-submitted" : "quiz"
  } else {
    optionMode = "review"
  }

  const isQuizDone = view === "quiz" && (submitted || showAnswerInQuiz)
  const studentIsRight =
    view === "quiz" && submitted && selectedKey === q.answer_key

  return (
    <div className={cn("flex flex-col gap-5", className)}>
      {/* ── Header: badges ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <QuestionTypeBadge type={q.question_type} />
        <BloomBadge level={q.cognitive_level} />
        {(q.learning_outcomes ?? []).map((code) => (
          <Badge
            key={code}
            variant="outline"
            className="border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-300"
            title="Chuẩn đầu ra"
          >
            <TargetIcon className="mr-1 size-3" />
            {code}
          </Badge>
        ))}
        {view === "review" && <QuestionStatusBadge status={q.review_status} />}
        {view === "review" && <VerifierBadge q={q} />}
        {q.topic && (
          <span className="ml-auto text-xs text-muted-foreground line-clamp-1 flex items-center gap-1">
            <BookOpenIcon className="size-3" />
            {q.topic}
          </span>
        )}
      </div>

      {/* ── Stem ───────────────────────────────────────────────────────── */}
      <section className="rounded-lg border bg-card p-4">
        <div className="flex items-baseline gap-2 mb-2 text-xs text-muted-foreground uppercase tracking-wide font-semibold">
          <FileTextIcon className="size-3.5" />
          Đề bài
          {index !== undefined && (
            <span className="font-mono">#{index + 1}</span>
          )}
        </div>
        <QuestionStem stem={q.stem} className="text-foreground" />
      </section>

      {/* ── Options ────────────────────────────────────────────────────── */}
      <section>
        <p className="text-xs text-muted-foreground uppercase tracking-wide font-semibold mb-2">
          Phương án
        </p>
        <QuestionOptions
          options={options}
          answerKey={q.answer_key ?? undefined}
          mode={optionMode}
          selectedKey={selectedKey}
          onSelect={(k) => view === "quiz" && !submitted && !showAnswerInQuiz && setSelectedKey(k)}
          explanationPerDistractor={
            optionMode === "review" || optionMode === "quiz-submitted"
              ? explanationsPerD
              : undefined
          }
        />

        {/* Quiz mode controls */}
        {view === "quiz" && (
          <div className="flex items-center gap-2 mt-3">
            {!submitted && !showAnswerInQuiz && (
              <>
                <Button
                  size="sm"
                  disabled={!selectedKey}
                  onClick={() => setSubmitted(true)}
                >
                  Nộp bài
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowAnswerInQuiz(true)}
                >
                  <EyeIcon className="size-3.5 mr-1" />
                  Xem đáp án
                </Button>
              </>
            )}
            {(submitted || showAnswerInQuiz) && (
              <>
                {submitted && (
                  <span
                    className={cn(
                      "text-sm font-medium flex items-center gap-1",
                      studentIsRight ? "text-emerald-600" : "text-rose-600"
                    )}
                  >
                    {studentIsRight ? (
                      <>
                        <CheckCircle2Icon className="size-4" /> Chính xác!
                      </>
                    ) : (
                      <>
                        <XCircleIcon className="size-4" /> Chưa đúng. Đáp án: {q.answer_key}
                      </>
                    )}
                  </span>
                )}
                {!submitted && showAnswerInQuiz && (
                  <span className="text-sm text-muted-foreground">
                    Đáp án: <span className="font-bold text-foreground">{q.answer_key}</span>
                  </span>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={() => {
                    setSelectedKey(null)
                    setSubmitted(false)
                    setShowAnswerInQuiz(false)
                  }}
                >
                  <RotateCcwIcon className="size-3.5 mr-1" />
                  Làm lại
                </Button>
              </>
            )}
          </div>
        )}
      </section>

      {/* ── Explanation correct ────────────────────────────────────────── */}
      {q.explanation_correct && (view === "review" || isQuizDone) && (
        <section className="rounded-lg border bg-blue-50/50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-900/50 p-4">
          <div className="flex items-center gap-1.5 mb-2 text-xs text-blue-700 dark:text-blue-400 uppercase tracking-wide font-semibold">
            <GraduationCapIcon className="size-3.5" />
            Hướng dẫn giải
          </div>
          <MathContent
            text={q.explanation_correct}
            className="text-sm text-foreground/90"
          />
        </section>
      )}

      {hasDetailedSolution && (view === "review" || isQuizDone) && (
        <section className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-1.5 mb-3 text-xs text-muted-foreground uppercase tracking-wide font-semibold">
            <GraduationCapIcon className="size-3.5" />
            Lời giải từng bước
          </div>

          {detailedSteps.length > 0 && (
            <ol className="space-y-3">
              {detailedSteps.map((step, idx) => (
                <li key={`${step.title ?? "step"}-${idx}`} className="flex gap-3">
                  <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {idx + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    {step.title && (
                      <p className="mb-1 text-sm font-medium text-foreground">
                        {step.title}
                      </p>
                    )}
                    <MathContent
                      text={step.content}
                      className="text-sm text-foreground/90"
                    />
                  </div>
                </li>
              ))}
            </ol>
          )}

          {detailedFinalAnswer && (
            <div className="mt-3 rounded-md border bg-muted/40 px-3 py-2 text-sm">
              <span className="font-medium text-muted-foreground">Kết quả: </span>
              <MathContent text={detailedFinalAnswer} inline className="text-foreground" />
            </div>
          )}

          {q.why_correct && (
            <div className="mt-3 border-t pt-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Vì sao đáp án đúng
              </p>
              <MathContent text={q.why_correct} className="text-sm text-foreground/90" />
            </div>
          )}
        </section>
      )}

      {whyOthersWrong.length > 0 && (view === "review" || isQuizDone) && (
        <section className="rounded-lg border bg-card p-4">
          <div className="mb-2 text-xs text-muted-foreground uppercase tracking-wide font-semibold">
            Vì sao các phương án khác sai
          </div>
          <div className="space-y-2">
            {whyOthersWrong.map((item, idx) => (
              <div key={`${item.option ?? "option"}-${idx}`} className="flex gap-2 text-sm">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted font-semibold">
                  {item.option}
                </span>
                <MathContent
                  text={item.reason}
                  className="min-w-0 flex-1 text-muted-foreground"
                />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Source quote (review only) ─────────────────────────────────── */}
      {view === "review" && q.source?.quote && (
        <section>
          <div className="flex items-center gap-1.5 mb-2 text-xs text-muted-foreground uppercase tracking-wide font-semibold">
            <FileTextIcon className="size-3.5" />
            Trích dẫn nguồn
            {q.source.quote_in_context === false && (
              <span className="ml-1 text-rose-600 normal-case font-normal">
                (không khớp context)
              </span>
            )}
          </div>
          <blockquote className="border-l-4 border-primary/40 pl-3 py-1 text-sm italic text-muted-foreground bg-muted/30 rounded-r">
            <MathContent text={`“${q.source.quote}”`} className="prose-mcq-compact" />
          </blockquote>
        </section>
      )}

      {/* ── Critic rubric (review only) ────────────────────────────────── */}
      {view === "review" && Object.keys(traits).length > 0 && (
        <section>
          <div className="flex items-center gap-1.5 mb-2 text-xs text-muted-foreground uppercase tracking-wide font-semibold">
            <StarIcon className="size-3.5" />
            Đánh giá Critic (RMTS)
          </div>
          <div className="flex flex-col gap-2.5 rounded-lg border bg-card p-3">
            {Object.entries(traits).map(([key, t]) => (
              <div key={key} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium">{TRAIT_LABELS[key] ?? key}</span>
                </div>
                <ScoreBar score={t.score} />
                {t.rationale && (
                  <MathContent
                    text={t.rationale}
                    className="prose-mcq-compact text-[11px] text-muted-foreground italic"
                  />
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Quick scores summary (review) ──────────────────────────────── */}
      {view === "review" && (
        <section className="grid grid-cols-3 gap-2">
          {q.judging?.grounding !== undefined && (
            <ScoreCell label="Grounding" score={q.judging.grounding} />
          )}
          {q.judging?.quality !== undefined && (
            <ScoreCell label="Quality" score={q.judging.quality} />
          )}
          {q.judging?.bloom_alignment !== undefined && (
            <ScoreCell label="Bloom" score={q.judging.bloom_alignment} />
          )}
        </section>
      )}

      {/* ── Pills row ──────────────────────────────────────────────────── */}
      {view === "review" && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <ScorePill label="G" score={q.judging?.grounding} />
          <ScorePill label="Q" score={q.judging?.quality} />
          <ScorePill label="B" score={q.judging?.bloom_alignment} />
          <ScorePill label="A" score={q.judging?.answer_prob} />
        </div>
      )}

      {/* ── Meta footer ───────────────────────────────────────────────── */}
      {view === "review" && (
        <section className="text-xs text-muted-foreground space-y-0.5 pt-3 border-t">
          {q.difficulty_target !== undefined && (
            <p>
              Độ khó target:{" "}
              <span className="font-mono">{q.difficulty_target?.toFixed(2)}</span>
              {q.difficulty_estimated !== undefined && (
                <>
                  {" "}· ước tính:{" "}
                  <span className="font-mono">
                    {q.difficulty_estimated.toFixed(2)}
                  </span>
                </>
              )}
            </p>
          )}
          {q.estimated_time_seconds !== undefined && (
            <p>
              Thời gian dự kiến:{" "}
              <span className="font-mono">{q.estimated_time_seconds}s</span>
            </p>
          )}
          <p>
            ID:{" "}
            <code className="text-[11px] bg-muted px-1 rounded">
              {q.question_id}
            </code>
          </p>
        </section>
      )}
    </div>
  )
}

function ScoreCell({ label, score }: { label: string; score: number }) {
  return (
    <div className="rounded-lg bg-muted/40 border p-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-lg font-bold font-mono leading-tight">
        {score.toFixed(2)}
      </p>
    </div>
  )
}
