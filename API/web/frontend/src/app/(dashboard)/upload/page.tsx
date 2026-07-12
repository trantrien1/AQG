"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { FileTextIcon, GraduationCapIcon, Loader2Icon, PlusIcon, SparklesIcon, TargetIcon, UploadIcon, XIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import {
  deleteJob,
  getPrepareStatus,
  preparePDF,
  startPreparedJob,
  uploadPDF,
  type PrepareStatus,
} from "@/lib/api"

export default function UploadPage() {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [dragging, setDragging] = useState(false)
  const [numQuestions, setNumQuestions] = useState(6)
  const [difficulty, setDifficulty] = useState("mixed")
  // Tắt để sinh nhanh hơn: câu hỏi chỉ có đề + phương án + đáp án đúng.
  const [includeExplanation, setIncludeExplanation] = useState(true)
  // Chuẩn đầu ra (CĐR): mỗi phần tử một mô tả; mã CĐR1, CĐR2... gán theo thứ tự.
  const [outcomes, setOutcomes] = useState<string[]>([])
  // Two-step upload: file được /prepare NGAY khi chọn (render trang + trích
  // dàn ý chạy nền); bấm Generate chỉ gửi config qua /start nên vào sinh luôn.
  const [prepareJobId, setPrepareJobId] = useState<string | null>(null)
  const [prepare, setPrepare] = useState<PrepareStatus | null>(null)

  const discardPrepared = (jobId: string | null) => {
    if (jobId) deleteJob(jobId).catch(() => {})
  }

  const handleFile = (f: File) => {
    if (f.type !== "application/pdf") {
      setError("Chỉ chấp nhận file PDF.")
      return
    }
    discardPrepared(prepareJobId)
    setPrepareJobId(null)
    setPrepare(null)
    setFile(f)
    setError("")
    // Prepare thất bại (mạng/backend) thì onSubmit tự fallback về /upload cũ.
    preparePDF(f)
      .then(({ job_id }) => {
        setPrepareJobId(job_id)
        setPrepare({ status: "preparing" })
      })
      .catch(() => setPrepareJobId(null))
  }

  const removeFile = () => {
    discardPrepared(prepareJobId)
    setPrepareJobId(null)
    setPrepare(null)
    setFile(null)
  }

  // Poll trạng thái prepare để hiện gợi ý (chủ đề, CĐR, số câu) lên form.
  useEffect(() => {
    if (!prepareJobId) return
    if (prepare && prepare.status !== "preparing" && prepare.status !== "none") return
    const timer = setInterval(() => {
      getPrepareStatus(prepareJobId)
        .then(setPrepare)
        .catch(() => {})
    }, 2000)
    return () => clearInterval(timer)
  }, [prepareJobId, prepare])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prepareJobId])

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError("Vui lòng chọn file PDF.")
      return
    }
    if (prepare?.status === "error") {
      setError(prepare.error || "Tài liệu không hợp lệ.")
      return
    }
    setLoading(true)
    setError("")
    const learningOutcomes = outcomes
      .map((desc, i) => ({ code: `CĐR${i + 1}`, description: desc.trim() }))
      .filter((o) => o.description)
    try {
      if (prepareJobId) {
        await startPreparedJob(prepareJobId, numQuestions, {
          difficulty,
          includeExplanation,
          learningOutcomes,
        })
        router.push(`/job/${prepareJobId}/generate`)
        return
      }
      const { job_id } = await uploadPDF(file, numQuestions, {
        directPdf: true,
        difficulty,
        includeExplanation,
        learningOutcomes,
      })
      router.push(`/job/${job_id}/generate`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Lỗi khi tải lên.")
      setLoading(false)
    }
  }

  const outline = prepare?.status === "ready" ? prepare.outline : null
  const suggestedOutcomes = (outline?.suggested_learning_outcomes ?? []).filter(
    (o) => o.description?.trim(),
  )

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="flex w-full max-w-2xl flex-col gap-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight">Tải lên PDF</h1>
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-5">
          <div
            className={`relative cursor-pointer rounded-xl border-2 border-dashed p-16 text-center transition-colors ${
              dragging
                ? "border-primary bg-primary/5"
                : file
                  ? "border-primary/40 bg-primary/5"
                  : "border-muted-foreground/25 hover:border-primary/50"
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
          >
            {file ? (
              <div className="flex flex-col items-center gap-3">
                <FileTextIcon className="size-14 text-primary" />
                <p className="font-medium">{file.name}</p>
                <p className="text-sm text-muted-foreground">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                <button
                  type="button"
                  className="absolute right-3 top-3 rounded-full p-1.5 hover:bg-muted"
                  onClick={(event) => { event.stopPropagation(); removeFile() }}
                >
                  <XIcon className="size-5 text-muted-foreground" />
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <UploadIcon className="size-14 text-muted-foreground" />
                <p className="text-lg font-medium">Kéo thả file PDF vào đây</p>
                <p className="text-sm text-muted-foreground">hoặc click để chọn file</p>
              </div>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]) }}
            />
          </div>

          {file && prepareJobId && (
            <div className="rounded-lg border bg-muted/30 p-4">
              {prepare?.status === "error" ? (
                <p className="text-sm text-destructive">
                  {prepare.error || "Tài liệu không hợp lệ."}
                </p>
              ) : outline ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-1.5 text-sm font-medium">
                    <SparklesIcon className="size-4 text-primary" />
                    Gợi ý từ tài liệu
                    {outline.document_title && (
                      <span className="font-normal text-muted-foreground">
                        — {outline.document_title}
                      </span>
                    )}
                  </div>
                  {(outline.topics?.length ?? 0) > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {outline.topics!.map((t) => (
                        <span
                          key={t}
                          className="rounded-full border bg-background px-2.5 py-0.5 text-xs text-muted-foreground"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {outline.suggested_num_questions ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setNumQuestions(outline.suggested_num_questions!)}
                      >
                        Dùng {outline.suggested_num_questions} câu như gợi ý
                      </Button>
                    ) : null}
                    {suggestedOutcomes.length > 0 && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setOutcomes(suggestedOutcomes.map((o) => o.description.trim()))
                        }
                      >
                        Dùng {suggestedOutcomes.length} chuẩn đầu ra gợi ý
                      </Button>
                    )}
                  </div>
                </div>
              ) : prepare?.status === "ready" ? (
                <p className="text-sm text-muted-foreground">
                  Tài liệu đã sẵn sàng{prepare.num_pages ? ` (${prepare.num_pages} trang)` : ""} —
                  bấm Generate để sinh câu hỏi ngay.
                </p>
              ) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2Icon className="size-4 animate-spin" />
                  {prepare?.message || "Đang đọc tài liệu để gợi ý cấu hình..."}
                </div>
              )}
            </div>
          )}

          <div className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm font-medium">Số câu hỏi</span>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min={1}
                max={30}
                value={numQuestions}
                onChange={(e) => setNumQuestions(Math.max(1, Math.min(30, Number(e.target.value) || 1)))}
                className="h-9 w-20 rounded-md border bg-background px-3 text-center text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <div className="flex gap-2">
                {[5, 6, 10].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setNumQuestions(n)}
                    className={`h-9 rounded-md border px-3 text-sm transition ${
                      numQuestions === n
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background hover:bg-accent"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm font-medium">Difficulty</span>
            <div className="grid grid-cols-2 gap-2 sm:flex">
              {[
                { id: "mixed", label: "Mixed" },
                { id: "easy", label: "Easy" },
                { id: "medium", label: "Medium" },
                { id: "hard", label: "Hard" },
              ].map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setDifficulty(item.id)}
                  className={`h-9 rounded-md border px-3 text-sm transition ${
                    difficulty === item.id
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background hover:bg-accent"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border p-4">
            <div className="flex flex-col gap-1">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <GraduationCapIcon className="size-4 text-muted-foreground" />
                Lời giải & giải thích
              </span>
              <p className="text-xs text-muted-foreground">
                Sinh lời giải từng bước, vì sao đáp án đúng và vì sao các phương án khác sai.
                Tắt để sinh nhanh hơn (chỉ có đề bài, phương án và đáp án đúng).
              </p>
            </div>
            <Switch
              checked={includeExplanation}
              onCheckedChange={(checked) => setIncludeExplanation(Boolean(checked))}
            />
          </div>

          <div className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <TargetIcon className="size-4 text-muted-foreground" />
                Chuẩn đầu ra <span className="font-normal text-muted-foreground">(tuỳ chọn)</span>
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setOutcomes((prev) => [...prev, ""])}
              >
                <PlusIcon className="mr-1 size-3.5" />
                Thêm chuẩn
              </Button>
            </div>
            {outcomes.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Mô tả các chuẩn đầu ra của học phần (một hoặc nhiều). Sau khi sinh xong,
                mỗi câu hỏi sẽ được tự động phân loại thuộc chuẩn đầu ra nào.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {outcomes.map((value, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="mt-2 shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                      CĐR{i + 1}
                    </span>
                    <textarea
                      value={value}
                      rows={2}
                      placeholder="VD: Vận dụng được tích phân xác định để tính diện tích, thể tích trong bài toán thực tế"
                      onChange={(e) =>
                        setOutcomes((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                      }
                      className="min-h-9 w-full resize-y rounded-md border bg-background px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <button
                      type="button"
                      title="Xoá chuẩn này"
                      className="mt-1.5 rounded-full p-1.5 hover:bg-muted"
                      onClick={() => setOutcomes((prev) => prev.filter((_, j) => j !== i))}
                    >
                      <XIcon className="size-4 text-muted-foreground" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && <p className="text-center text-sm text-destructive">{error}</p>}

          <Button type="submit" disabled={loading || !file} className="h-12 w-full text-base">
            {loading
              ? <><Loader2Icon className="mr-2 size-4 animate-spin" />Đang xử lý...</>
              : <><UploadIcon className="mr-2 size-4" />Tải lên & sinh câu hỏi</>}
          </Button>
        </form>
      </div>
    </div>
  )
}
