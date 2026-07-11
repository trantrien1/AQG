"use client"

import { CheckIcon, XIcon } from "lucide-react"
import { MathContent } from "@/components/math-content"
import { cn } from "@/lib/utils"
import type { OptionItem } from "@/lib/api"

export type OptionMode =
  | "review"          // Chế độ xem (giáo viên duyệt) — hiện đáp án đúng/sai luôn
  | "quiz"            // Chế độ làm bài — chưa submit, chỉ select
  | "quiz-submitted"  // Chế độ làm bài — đã submit, hiện kết quả
  | "preview"         // Chỉ xem trong card (compact, không show correct)

interface OptionsListProps {
  options: OptionItem[]
  answerKey?: string
  mode: OptionMode
  selectedKey?: string | null
  onSelect?: (key: string) => void
  /** Optional: explanation cho từng distractor — chỉ hiện trong review giáo viên. */
  explanationPerDistractor?: Record<string, string>
  className?: string
  /** Compact = font nhỏ, padding ít hơn (dùng trong card) */
  compact?: boolean
}

/**
 * Hiển thị danh sách phương án A/B/C/D.
 *
 * - mode='review' (mặc định cho dashboard duyệt): đáp án đúng được highlight xanh,
 *   distractor có thể kèm rationale.
 * - mode='quiz': cho phép user click chọn, chưa hiện đáp án đúng.
 * - mode='quiz-submitted': đã submit, hiện đúng/sai trên cả option đã chọn lẫn
 *   đáp án đúng thật, nhưng không lộ rationale distractor dưới từng option.
 * - mode='preview': hiện 4 option ngắn gọn không nhấn mạnh đáp án (cho card list).
 */
export function QuestionOptions({
  options,
  answerKey,
  mode,
  selectedKey,
  onSelect,
  explanationPerDistractor,
  className,
  compact = false,
}: OptionsListProps) {
  if (!options?.length) {
    return (
      <p className="text-sm text-muted-foreground italic">(Chưa có phương án)</p>
    )
  }

  return (
    <ol
      className={cn(
        "flex flex-col",
        compact ? "gap-1.5" : "gap-2",
        className
      )}
    >
      {options.map((opt) => {
        const isCorrect = answerKey != null && opt.key === answerKey
        const isSelected = selectedKey === opt.key
        const isClickable = mode === "quiz" && Boolean(onSelect)
        const showOptionRationale = mode === "review"
        const explanation = showOptionRationale && !isCorrect
          ? explanationPerDistractor?.[opt.key]
          : undefined

        // ─── Style state ────────────────────────────────────────────────
        const showResult = mode === "review" || mode === "quiz-submitted"
        const userIsWrong =
          mode === "quiz-submitted" && isSelected && !isCorrect
        const userIsRight =
          mode === "quiz-submitted" && isSelected && isCorrect

        let stateClass = ""
        if (mode === "preview") {
          stateClass = "border-border bg-card hover:bg-accent/40"
        } else if (showResult && isCorrect) {
          stateClass =
            "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40"
        } else if (showResult && !isCorrect && isSelected) {
          stateClass =
            "border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40"
        } else if (mode === "quiz" && isSelected) {
          stateClass =
            "border-primary bg-primary/5 ring-2 ring-primary/30"
        } else {
          stateClass = "border-border bg-card hover:bg-accent/30"
        }

        const KeyBadge = () => (
          <span
            className={cn(
              "flex shrink-0 items-center justify-center rounded-full font-bold font-sans",
              compact ? "size-6 text-xs" : "size-7 text-sm",
              showResult && isCorrect
                ? "bg-emerald-500 text-white"
                : userIsWrong
                ? "bg-rose-500 text-white"
                : userIsRight
                ? "bg-emerald-500 text-white"
                : isSelected
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-foreground"
            )}
          >
            {showResult && isCorrect ? (
              <CheckIcon className="size-3.5" />
            ) : userIsWrong ? (
              <XIcon className="size-3.5" />
            ) : (
              opt.key
            )}
          </span>
        )

        return (
          <li
            key={opt.key}
            className={cn(
              "flex flex-col gap-1 rounded-lg border transition-all",
              compact ? "p-2" : "p-3",
              stateClass,
              isClickable && "cursor-pointer focus-within:ring-2 focus-within:ring-primary"
            )}
            onClick={() => isClickable && onSelect?.(opt.key)}
          >
            <div className="flex items-start gap-3">
              <KeyBadge />
              <div className="flex-1 min-w-0">
                <MathContent
                  text={opt.text}
                  className={cn(
                    compact ? "text-sm prose-mcq-compact" : "text-[15px]"
                  )}
                />
                {explanation && (
                  <MathContent
                    text={explanation}
                    className={cn(
                      "italic text-muted-foreground/90 leading-relaxed mt-1",
                      compact ? "text-[11px]" : "text-xs"
                    )}
                  />
                )}
                {showOptionRationale && opt.error_type && !explanation && (
                  <p className="text-[11px] text-muted-foreground/70 mt-0.5">
                    <span className="font-mono">{opt.error_type}</span>
                  </p>
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
