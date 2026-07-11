"use client"

import { ChevronRightIcon, BookmarkIcon } from "lucide-react"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { BloomBadge } from "@/components/bloom/bloom-level-selector"
import { MathContent } from "@/components/math-content"
import { QuestionStem } from "./question-stem"
import { QuestionStatusBadge } from "./question-status-badge"
import { QuestionTypeBadge } from "./question-type-badge"
import { ScorePill } from "./score-pill"
import { cn } from "@/lib/utils"
import type { Question } from "@/lib/api"

interface QuestionCardProps {
  question: Question
  index: number
  onClick?: () => void
  className?: string
}

export function QuestionCard({
  question: q,
  index,
  onClick,
  className,
}: QuestionCardProps) {
  const options = Array.isArray(q.options) ? q.options : []
  const correctOpt = options.find((o) => o.key === q.answer_key)

  return (
    <Card
      onClick={onClick}
      className={cn(
        "group cursor-pointer transition-all hover:shadow-md hover:border-primary/40 focus-within:ring-2 focus-within:ring-primary/40",
        className
      )}
      tabIndex={0}
      role="button"
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && onClick) {
          e.preventDefault()
          onClick()
        }
      }}
    >
      <CardHeader className="pb-2 gap-2">
        {/* Top row: index + status + type */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs text-muted-foreground">#{index + 1}</span>
            <QuestionTypeBadge type={q.question_type} />
            <BloomBadge level={q.cognitive_level} />
          </div>
          <QuestionStatusBadge status={q.review_status} />
        </div>

        {/* Topic */}
        {q.topic && (
          <p className="flex items-center gap-1 text-xs text-muted-foreground line-clamp-1">
            <BookmarkIcon className="size-3 shrink-0" />
            <span className="truncate">{q.topic}</span>
          </p>
        )}

        {/* Stem (có math/markdown) */}
        <QuestionStem
          stem={q.stem}
          compact
          truncated
          className="text-foreground"
        />
      </CardHeader>

      <CardContent className="flex flex-col gap-2 pt-0">
        {/* Đáp án đúng (chỉ 1 dòng compact) */}
        {correctOpt && (
          <div className="flex items-start gap-2 rounded-md border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-1.5">
            <span className="flex shrink-0 size-5 items-center justify-center rounded-full bg-emerald-500 text-white text-[11px] font-bold">
              {correctOpt.key}
            </span>
            <div className="flex-1 min-w-0 text-sm text-emerald-900 dark:text-emerald-200 line-clamp-1">
              <MathContent
                text={correctOpt.text}
                className="prose-mcq-compact"
              />
            </div>
          </div>
        )}

        {/* Footer: scores + chevron */}
        <div className="flex items-center justify-between gap-2 pt-1.5 border-t">
          <div className="flex items-center gap-1 flex-wrap">
            <ScorePill label="G" score={q.judging?.grounding} />
            <ScorePill label="Q" score={q.judging?.quality} />
            <ScorePill label="B" score={q.judging?.bloom_alignment} />
          </div>
          <span className="text-xs text-primary opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-0.5 shrink-0">
            Chi tiết
            <ChevronRightIcon className="size-3" />
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
