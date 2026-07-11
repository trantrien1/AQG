"use client"

import * as React from "react"
import Link from "next/link"
import {
  Loader2Icon, FileTextIcon, ClockIcon, CheckCircle2Icon,
  XCircleIcon, AlertTriangleIcon, ArrowRightIcon, UploadIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/empty-state"
import { listJobs, type JobMeta } from "@/lib/api"
import { cn } from "@/lib/utils"

const STATUS_CONFIG: Record<string, { label: string; cls: string; icon: React.ComponentType<{ className?: string }> }> = {
  done: {
    label: "Hoàn thành",
    cls: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900",
    icon: CheckCircle2Icon,
  },
  running: {
    label: "Đang chạy",
    cls: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-900",
    icon: Loader2Icon,
  },
  pending: {
    label: "Chờ xử lý",
    cls: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900",
    icon: ClockIcon,
  },
  // Two-step upload: job đã /prepare nhưng chưa bấm Generate.
  preparing: {
    label: "Đang đọc tài liệu",
    cls: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-900",
    icon: Loader2Icon,
  },
  prepared: {
    label: "Chưa sinh câu hỏi",
    cls: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900",
    icon: ClockIcon,
  },
  error: {
    label: "Lỗi",
    cls: "bg-rose-100 text-rose-700 border-rose-200 dark:bg-rose-950 dark:text-rose-300 dark:border-rose-900",
    icon: XCircleIcon,
  },
}

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? {
    label: status,
    cls: "bg-muted text-muted-foreground border-border",
    icon: AlertTriangleIcon,
  }
  const Icon = cfg.icon
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        cfg.cls
      )}
    >
      <Icon className={cn("size-3", status === "running" && "animate-spin")} />
      {cfg.label}
    </span>
  )
}

function getNextStep(status: string, jobId: string): { url: string; label: string } {
  if (status === "done") return { url: `/job/${jobId}/questions`, label: "Xem câu hỏi" }
  if (status === "running") return { url: `/job/${jobId}/generate`, label: "Theo dõi tiến độ" }
  return { url: `/job/${jobId}/generate`, label: "Tiếp tục" }
}

export default function JobsPage() {
  const [jobs, setJobs] = React.useState<JobMeta[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState("")

  React.useEffect(() => {
    listJobs()
      .then((data) => setJobs(data.jobs ?? []))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Loader2Icon className="size-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Lịch sử Jobs</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            <span className="text-foreground font-medium">{jobs.length}</span>{" "}
            phiên xử lý đã có
          </p>
        </div>
        <Button render={<Link href="/upload" />}>
          <UploadIcon className="size-4 mr-2" />
          Tạo job mới
        </Button>
      </div>

      {error && (
        <p className="text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      {jobs.length === 0 && !error && (
        <EmptyState
          variant="jobs"
          actionLabel="Tải lên PDF"
          onAction={() => (window.location.href = "/upload")}
        />
      )}

      {jobs.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {jobs.map((job) => {
            const next = getNextStep(job.status, job.job_id)
            return (
              <Card
                key={job.job_id}
                className="hover:shadow-md transition-shadow group"
              >
                <CardHeader className="pb-2 gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="text-sm font-medium line-clamp-1 leading-snug">
                      <FileTextIcon className="size-3.5 inline mr-1 -mt-0.5" />
                      {job.pdf_name ?? "Untitled job"}
                    </CardTitle>
                    <StatusBadge status={job.status} />
                  </div>
                  <CardDescription className="text-[11px] font-mono text-muted-foreground/80">
                    {job.job_id}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {job.num_questions !== undefined && (
                      <span>
                        <span className="font-mono font-medium text-foreground">
                          {job.num_questions}
                        </span>{" "}
                        câu hỏi
                      </span>
                    )}
                  </div>
                  {job.created_at && (
                    <p className="text-[11px] text-muted-foreground">
                      <ClockIcon className="size-3 inline mr-0.5 -mt-0.5" />
                      {new Date(job.created_at).toLocaleString()}
                    </p>
                  )}
                  {job.error && (
                    <Badge variant="destructive" className="text-[11px]">
                      <AlertTriangleIcon className="size-3 mr-1" />
                      <span className="truncate max-w-[200px]">{job.error}</span>
                    </Badge>
                  )}
                  <Button
                    render={<Link href={next.url} />}
                    size="sm"
                    variant="ghost"
                    className="w-full justify-between mt-1 group-hover:bg-accent"
                  >
                    {next.label}
                    <ArrowRightIcon className="size-3.5" />
                  </Button>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
