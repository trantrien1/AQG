"use client"

import * as React from "react"
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import {
  CheckIcon, XIcon, ClipboardCopyIcon, FileTextIcon,
  EyeIcon, GraduationCapIcon,
} from "lucide-react"
import { QuestionDetailView } from "@/components/question/question-detail-view"
import type { Question } from "@/lib/api"

interface Props {
  question: Question | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onReview?: (id: string, action: "approve" | "reject") => void
}

export function QuestionDetailSheet({
  question: q,
  open,
  onOpenChange,
  onReview,
}: Props) {
  const [copied, setCopied] = React.useState(false)

  if (!q) return null

  const options = Array.isArray(q.options) ? q.options : []

  const copyText = async () => {
    const lines = [
      `Câu hỏi: ${q.stem}`,
      ...options.map(
        (o) => `${o.key}. ${o.text}${o.key === q.answer_key ? "  ✓" : ""}`
      ),
      `Đáp án đúng: ${q.answer_key}`,
      q.explanation_correct ? `\nGiải thích: ${q.explanation_correct}` : "",
    ]
    await navigator.clipboard.writeText(lines.filter(Boolean).join("\n"))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const canReview =
    onReview &&
    (q.review_status === "pending_review" || q.review_status === "needs_revision")

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl flex flex-col p-0 gap-0">
        {/* ── Header sticky ───────────────────────────────────────────── */}
        <SheetHeader className="px-5 pt-5 pb-3 border-b shrink-0">
          <SheetTitle className="text-lg">Chi tiết câu hỏi</SheetTitle>
          <SheetDescription className="text-xs">
            <code className="bg-muted px-1 rounded">{q.question_id}</code>
            {q.kc_ids?.[0] && <span className="ml-1">· KC: {q.kc_ids[0]}</span>}
          </SheetDescription>
        </SheetHeader>

        {/* ── Body với 2 tab: Review (giáo viên) + Quiz (học sinh) ──── */}
        <Tabs defaultValue="review" className="flex-1 flex flex-col overflow-hidden">
          <div className="px-5 pt-3 shrink-0 border-b">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="review" className="gap-1">
                <EyeIcon className="size-3.5" />
                Xem & duyệt
              </TabsTrigger>
              <TabsTrigger value="quiz" className="gap-1">
                <GraduationCapIcon className="size-3.5" />
                Làm bài
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="review" className="flex-1 overflow-y-auto px-5 py-4 m-0">
            <QuestionDetailView key={`review-${q.question_id}`} question={q} view="review" />
          </TabsContent>

          <TabsContent value="quiz" className="flex-1 overflow-y-auto px-5 py-4 m-0">
            <QuestionDetailView key={`quiz-${q.question_id}`} question={q} view="quiz" />
          </TabsContent>
        </Tabs>

        {/* ── Sticky action bar ──────────────────────────────────────── */}
        <div className="flex gap-2 px-5 py-3 border-t bg-background shrink-0">
          <Button
            size="sm"
            variant="outline"
            onClick={copyText}
            className="flex-1"
          >
            <ClipboardCopyIcon className="size-3.5 mr-1" />
            {copied ? "Đã copy" : "Copy"}
          </Button>
          {canReview && (
            <>
              <Button
                size="sm"
                variant="outline"
                className="flex-1 text-emerald-700 border-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
                onClick={() => onReview!(q.question_id, "approve")}
              >
                <CheckIcon className="size-3.5 mr-1" />
                Duyệt
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1 text-rose-700 border-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/30"
                onClick={() => onReview!(q.question_id, "reject")}
              >
                <XIcon className="size-3.5 mr-1" />
                Từ chối
              </Button>
            </>
          )}
          {!canReview && (
            <Button size="sm" variant="outline" className="flex-1" disabled>
              <FileTextIcon className="size-3.5 mr-1" />
              {q.review_status === "approved" ? "Đã duyệt" : "Đã từ chối"}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
