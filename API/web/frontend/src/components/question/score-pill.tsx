"use client"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const SCORE_INFO: Record<string, { label: string; full: string }> = {
  G: {
    label: "Grounding",
    full: "Mức độ stem/đáp án bám sát ngữ cảnh tài liệu nguồn (0..1).",
  },
  Q: {
    label: "Quality",
    full: "Trung bình 5 traits của Critic: clarity, cognitive depth, bloom alignment, distractor plausibility, answer uniqueness.",
  },
  B: {
    label: "Bloom",
    full: "Mức độ phù hợp với Bloom level đã yêu cầu.",
  },
  A: {
    label: "Answer prob",
    full: "Xác suất NLI (đáp án đúng được hỗ trợ bởi context).",
  },
}

function colorFor(score: number): string {
  if (score >= 0.8) return "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40"
  if (score >= 0.6) return "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40"
  return "text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40"
}

export function ScorePill({
  label,
  score,
  className,
}: {
  label: keyof typeof SCORE_INFO | string
  score?: number | null
  className?: string
}) {
  if (score == null || Number.isNaN(score)) return null
  const info = SCORE_INFO[label as string]
  const color = colorFor(score)

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-mono font-medium cursor-help",
              color,
              className
            )}
          >
            <span className="font-sans font-semibold">{label}</span>
            <span>{score.toFixed(2)}</span>
          </span>
        }
      />
      <TooltipContent side="top" className="max-w-[260px]">
        <p className="font-medium">{info?.label ?? label}</p>
        {info?.full && (
          <p className="text-[11px] mt-0.5 opacity-90">{info.full}</p>
        )}
      </TooltipContent>
    </Tooltip>
  )
}
