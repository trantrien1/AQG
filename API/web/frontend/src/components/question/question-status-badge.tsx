"use client"

import {
  CheckCircle2Icon,
  XCircleIcon,
  ClockIcon,
  AlertTriangleIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"

type ReviewStatus = "pending_review" | "approved" | "rejected" | "needs_revision" | string

const STATUS_CONFIG: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  pending_review: {
    label: "Chờ duyệt",
    icon: ClockIcon,
    cls: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 border-slate-200 dark:border-slate-700",
  },
  approved: {
    label: "Đã duyệt",
    icon: CheckCircle2Icon,
    cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900",
  },
  rejected: {
    label: "Từ chối",
    icon: XCircleIcon,
    cls: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300 border-rose-200 dark:border-rose-900",
  },
  needs_revision: {
    label: "Cần sửa",
    icon: AlertTriangleIcon,
    cls: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200 border-amber-200 dark:border-amber-900",
  },
}

export function QuestionStatusBadge({
  status,
  className,
}: {
  status?: ReviewStatus
  className?: string
}) {
  const cfg = STATUS_CONFIG[status ?? "pending_review"] ?? STATUS_CONFIG.pending_review
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
