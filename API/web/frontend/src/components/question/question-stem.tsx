"use client"

import { MathContent } from "@/components/math-content"
import { cn } from "@/lib/utils"

interface QuestionStemProps {
  stem?: string
  className?: string
  /** Hiển thị compact trong card list */
  compact?: boolean
  /** Số thứ tự #N hiển thị trước stem */
  index?: number
  /** Limit max-height + show fade khi quá dài (chỉ trong compact) */
  truncated?: boolean
}

/**
 * Render đề bài câu hỏi với hỗ trợ markdown + LaTeX + code.
 * Compact mode dùng trong card list, full mode dùng trong sheet/page chi tiết.
 */
export function QuestionStem({
  stem,
  className,
  compact = false,
  index,
  truncated = false,
}: QuestionStemProps) {
  if (!stem) {
    return (
      <p className="text-sm italic text-muted-foreground">(Không có nội dung đề bài)</p>
    )
  }

  return (
    <div className={cn("relative", className)}>
      {index !== undefined && (
        <span className="text-muted-foreground font-mono text-sm mr-2 select-none">
          #{index + 1}
        </span>
      )}
      <MathContent
        text={stem}
        inline={false}
        className={cn(
          compact && "prose-mcq-compact text-[14px] leading-relaxed",
          !compact && "text-[15px] leading-relaxed",
          truncated && "max-h-[7.5rem] overflow-hidden"
        )}
      />
      {truncated && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-card to-transparent"
        />
      )}
    </div>
  )
}
