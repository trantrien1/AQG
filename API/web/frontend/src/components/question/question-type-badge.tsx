"use client"

import { CheckSquareIcon, ListChecksIcon, ToggleLeftIcon, FileQuestionIcon } from "lucide-react"
import { cn } from "@/lib/utils"

type QuestionTypeId = "single_choice" | "multiple_choice" | "true_false" | "fill_blank" | string

const TYPE_CONFIG: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  single_choice: {
    label: "Trắc nghiệm",
    icon: CheckSquareIcon,
    cls: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300 border-blue-200 dark:border-blue-900",
  },
  multiple_choice: {
    label: "Nhiều lựa chọn",
    icon: ListChecksIcon,
    cls: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300 border-violet-200 dark:border-violet-900",
  },
  true_false: {
    label: "Đúng / Sai",
    icon: ToggleLeftIcon,
    cls: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300 border-amber-200 dark:border-amber-900",
  },
  fill_blank: {
    label: "Điền chỗ trống",
    icon: FileQuestionIcon,
    cls: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300 border-cyan-200 dark:border-cyan-900",
  },
}

export function QuestionTypeBadge({
  type,
  className,
}: {
  type?: QuestionTypeId | null
  className?: string
}) {
  const cfg = TYPE_CONFIG[type ?? "single_choice"] ?? TYPE_CONFIG.single_choice
  const Icon = cfg.icon
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        cfg.cls,
        className
      )}
    >
      <Icon className="size-3" />
      {cfg.label}
    </span>
  )
}
