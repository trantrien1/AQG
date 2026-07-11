"use client"

import React from "react"
import { CheckIcon, EyeIcon, BookOpenIcon, CalculatorIcon, BrainIcon, LayersIcon } from "lucide-react"
import type { BloomLevel } from "@/lib/api"

export const BLOOM_LEVELS: {
  id: BloomLevel | "mixed"
  label: string
  short: string
  description: string
  icon: React.ComponentType<{ className?: string }>
  // Tailwind classes
  ring: string
  bg: string
  border: string
  text: string
  badge: string
}[] = [
  {
    id: "mixed",
    label: "Hỗn hợp",
    short: "Mixed",
    description: "Phân bố cân bằng theo Bloom (25/35/30/10%) — đa dạng nhất",
    icon: LayersIcon,
    ring: "ring-slate-500/60",
    bg: "bg-slate-500/5",
    border: "border-slate-300 dark:border-slate-700",
    text: "text-slate-600 dark:text-slate-300",
    badge: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  },
  {
    id: "Nhận biết",
    label: "Nhận biết",
    short: "Remember",
    description: "Nhớ định nghĩa, ký hiệu, sự kiện. Câu hỏi dễ, trực tiếp.",
    icon: EyeIcon,
    ring: "ring-blue-500/60",
    bg: "bg-blue-500/5",
    border: "border-blue-300 dark:border-blue-800",
    text: "text-blue-600 dark:text-blue-300",
    badge: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  },
  {
    id: "Thông hiểu",
    label: "Thông hiểu",
    short: "Understand",
    description: "Giải thích, so sánh, nhận diện tính chất. Hiểu khái niệm.",
    icon: BookOpenIcon,
    ring: "ring-emerald-500/60",
    bg: "bg-emerald-500/5",
    border: "border-emerald-300 dark:border-emerald-800",
    text: "text-emerald-600 dark:text-emerald-300",
    badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  },
  {
    id: "Vận dụng",
    label: "Vận dụng",
    short: "Apply",
    description: "Tính toán, áp dụng công thức vào tình huống cụ thể.",
    icon: CalculatorIcon,
    ring: "ring-orange-500/60",
    bg: "bg-orange-500/5",
    border: "border-orange-300 dark:border-orange-800",
    text: "text-orange-600 dark:text-orange-300",
    badge: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  },
  {
    id: "Vận dụng cao",
    label: "Vận dụng cao",
    short: "Analyze",
    description: "Suy luận nhiều bước, tích hợp khái niệm, có bẫy misconception.",
    icon: BrainIcon,
    ring: "ring-rose-500/60",
    bg: "bg-rose-500/5",
    border: "border-rose-300 dark:border-rose-800",
    text: "text-rose-600 dark:text-rose-300",
    badge: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  },
]

export function bloomBadgeClass(level: string | undefined): string {
  const found = BLOOM_LEVELS.find((b) => b.id === level || b.label === level)
  return found?.badge ?? "bg-muted text-muted-foreground"
}

export function BloomBadge({ level }: { level: string | undefined }) {
  const found = BLOOM_LEVELS.find((b) => b.id === level || b.label === level)
  if (!found) return null
  const Icon = found.icon
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${found.badge}`}>
      <Icon className="size-3" />
      {found.label}
    </span>
  )
}

interface Props {
  value: BloomLevel | "mixed"
  onChange: (v: BloomLevel | "mixed") => void
}

export function BloomLevelSelector({ value, onChange }: Props) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {BLOOM_LEVELS.map((b) => {
        const Icon = b.icon
        const selected = value === b.id
        return (
          <button
            type="button"
            key={b.id}
            onClick={() => onChange(b.id)}
            className={`
              relative text-left rounded-lg border p-4 transition-all
              ${selected
                ? `${b.bg} ${b.border} ring-2 ${b.ring} shadow-sm`
                : "border-border bg-card hover:bg-accent/30"}
            `}
          >
            {/* Header */}
            <div className="flex items-center gap-2 mb-2">
              <span className={`flex size-8 items-center justify-center rounded-md ${b.bg}`}>
                <Icon className={`size-4 ${b.text}`} />
              </span>
              <div className="flex-1 min-w-0">
                <p className={`font-semibold text-sm leading-tight ${selected ? b.text : ""}`}>
                  {b.label}
                </p>
                <p className="text-[11px] text-muted-foreground">{b.short}</p>
              </div>
              {selected && (
                <span className={`flex size-5 items-center justify-center rounded-full ${b.bg}`}>
                  <CheckIcon className={`size-3 ${b.text}`} />
                </span>
              )}
            </div>
            {/* Description */}
            <p className="text-xs text-muted-foreground leading-snug">{b.description}</p>
          </button>
        )
      })}
    </div>
  )
}
