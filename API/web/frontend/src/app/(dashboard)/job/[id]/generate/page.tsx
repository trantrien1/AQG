"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { AlertTriangleIcon, CheckCircleIcon, Loader2Icon, RotateCcwIcon, XCircleIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { getJobConfig, pollJobStatus, startGenerate, type JobConfig, type JobStatus } from "@/lib/api"

type Phase = "loading" | "running" | "done" | "error"

export default function GeneratePage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [phase, setPhase] = useState<Phase>("loading")
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [config, setConfig] = useState<JobConfig>({})
  const [errorMsg, setErrorMsg] = useState("")
  const [retrying, setRetrying] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const doPoll = useCallback(async () => {
    try {
      const next = await pollJobStatus(id)
      setStatus(next)
      if (next.status === "done" || next.status === "cancelled") {
        stopPoll()
        setPhase("done")
      } else if (next.status === "error" || next.status === "failed") {
        stopPoll()
        setPhase("error")
        setErrorMsg(next.error ?? next.message ?? "Lỗi không xác định")
      } else {
        setPhase("running")
      }
    } catch (err: unknown) {
      stopPoll()
      setPhase("error")
      setErrorMsg(err instanceof Error ? err.message : "Lỗi polling")
    }
  }, [id])

  useEffect(() => {
    getJobConfig(id)
      .then(({ config: loaded }) => setConfig(loaded ?? {}))
      .catch(() => setConfig({}))
      .finally(() => {
        doPoll()
        if (!pollRef.current) pollRef.current = setInterval(doPoll, 1500)
      })
    return () => stopPoll()
  }, [id, doPoll])

  const handleRetry = async () => {
    setRetrying(true)
    setErrorMsg("")
    setPhase("running")
    try {
      await startGenerate(id, {
        numQuestions: config.num_questions ?? status?.target_accepted ?? 6,
        bloomLevel: config.bloom_level ?? "mixed",
        difficulty: config.difficulty ?? "mixed",
      })
      await doPoll()
      if (!pollRef.current) pollRef.current = setInterval(doPoll, 1500)
    } catch (err: unknown) {
      setPhase("error")
      setErrorMsg(err instanceof Error ? err.message : "Lỗi khi chạy lại")
    } finally {
      setRetrying(false)
    }
  }

  const progressPct = Math.round((status?.progress ?? 0) * 100)
  const targetAccepted = status?.target_accepted ?? config.num_questions ?? 0
  const acceptedCount = status?.accepted ?? 0
  const rejectedCount = status?.rejected_count ?? 0
  const partial = Boolean(status?.partial)

  if (phase === "loading") {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Loader2Icon className="size-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight">Sinh câu hỏi từ PDF</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Job <code className="rounded bg-muted px-1 py-0.5 text-xs">{id}</code> chạy bằng Direct_PDF_Mode.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {phase === "running" ? "Đang sinh câu hỏi" : phase === "done" ? "Hoàn thành" : "Lỗi"}
          </CardTitle>
          <CardDescription>
            Hệ thống gửi trực tiếp PDF cho mô hình và lưu kết quả vào job hiện tại.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {phase === "running" && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <Loader2Icon className="size-5 shrink-0 animate-spin text-primary" />
                <p className="font-medium">Đang xử lý PDF...</p>
              </div>
              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{status?.message}</span>
                  <span>{progressPct}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-2 rounded-full bg-primary transition-all duration-700" style={{ width: `${progressPct}%` }} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-3 text-center">
                  <p className="text-2xl font-bold text-green-600">{acceptedCount}/{targetAccepted}</p>
                  <p className="text-xs text-muted-foreground">Accepted</p>
                </div>
                <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-center">
                  <p className="text-2xl font-bold text-red-500">{rejectedCount}</p>
                  <p className="text-xs text-muted-foreground">Rejected</p>
                </div>
              </div>
            </div>
          )}

          {phase === "done" && (
            <div className="flex flex-col items-center gap-4 py-4">
              {partial ? <AlertTriangleIcon className="size-12 text-amber-500" /> : <CheckCircleIcon className="size-12 text-green-500" />}
              <div className="text-center">
                <p className="text-lg font-medium">{partial ? "Chưa đủ số câu" : "Hoàn thành!"}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {acceptedCount}/{targetAccepted} câu được chấp nhận
                </p>
              </div>
              {partial && (
                <div className="w-full rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
                  {status?.message ?? "Mô hình trả về ít câu hơn yêu cầu."}
                </div>
              )}
              <Button onClick={() => router.push(`/job/${id}/questions`)} className="w-full">
                Xem câu hỏi
              </Button>
            </div>
          )}

          {phase === "error" && (
            <div className="flex flex-col items-center gap-4 py-4">
              <XCircleIcon className="size-10 text-destructive" />
              <p className="font-medium text-destructive">Lỗi</p>
              <p className="break-all text-center text-sm text-muted-foreground">{errorMsg}</p>
              <Button variant="outline" onClick={handleRetry} disabled={retrying} className="w-full">
                {retrying ? <><Loader2Icon className="mr-2 size-4 animate-spin" />Đang chạy lại...</> : <><RotateCcwIcon className="mr-2 size-4" />Chạy lại Direct PDF</>}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
