"use client"

// Phản hồi người dùng cho từng câu hỏi (RLHF-style):
// 👍/👎 + tag lý do + bình luận -> backend tổng hợp thành hồ sơ sở thích
// và tiêm vào prompt khi sinh lại câu hỏi.

import * as React from "react"
import { Loader2Icon, ThumbsDownIcon, ThumbsUpIcon, Trash2Icon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { QuestionStem } from "@/components/question/question-stem"
import { cn } from "@/lib/utils"
import type { FeedbackRating, Question, QuestionFeedback } from "@/lib/api"

// Khớp với từ vựng tag ở pipeline/feedback.py (TAG_LABELS / *_TAG_DIRECTIVES).
export const FEEDBACK_TAGS: Record<FeedbackRating, Array<{ id: string; label: string }>> = {
  down: [
    { id: "too_easy", label: "Quá dễ" },
    { id: "too_hard", label: "Quá khó" },
    { id: "unclear", label: "Đề khó hiểu" },
    { id: "wrong_answer", label: "Nghi sai đáp án" },
    { id: "bad_distractors", label: "Phương án nhiễu kém" },
    { id: "not_relevant", label: "Lệch tài liệu" },
    { id: "duplicate", label: "Trùng dạng câu khác" },
  ],
  up: [
    { id: "good_difficulty", label: "Độ khó phù hợp" },
    { id: "good_context", label: "Ngữ cảnh thực tế hay" },
    { id: "good_explanation", label: "Giải thích rõ" },
    { id: "good_distractors", label: "Nhiễu chất lượng" },
  ],
}

/** Cặp nút 👍/👎 gọn cho một dòng trong bảng câu hỏi. */
export function FeedbackThumbs({
  feedback,
  onOpen,
}: {
  feedback?: QuestionFeedback
  onOpen: (rating: FeedbackRating) => void
}) {
  return (
    <div className="flex gap-1">
      <button
        type="button"
        title={feedback?.rating === "up" ? "Đã thích — sửa phản hồi" : "Thích câu này"}
        onClick={(e) => {
          e.stopPropagation()
          onOpen("up")
        }}
        className={cn(
          "rounded-md border p-1.5 transition",
          feedback?.rating === "up"
            ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
            : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
        )}
      >
        <ThumbsUpIcon className="size-3.5" />
      </button>
      <button
        type="button"
        title={feedback?.rating === "down" ? "Đã chê — sửa phản hồi" : "Chê câu này (sẽ được sinh lại)"}
        onClick={(e) => {
          e.stopPropagation()
          onOpen("down")
        }}
        className={cn(
          "rounded-md border p-1.5 transition",
          feedback?.rating === "down"
            ? "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
            : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
        )}
      >
        <ThumbsDownIcon className="size-3.5" />
      </button>
    </div>
  )
}

/** Dialog nhập phản hồi chi tiết: rating + tag lý do + bình luận. */
export function FeedbackDialog({
  open,
  onOpenChange,
  question,
  initialRating,
  existing,
  saving,
  onSave,
  onClear,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  question: Question | null
  initialRating: FeedbackRating
  existing?: QuestionFeedback
  saving: boolean
  onSave: (payload: { rating: FeedbackRating; tags: string[]; comment: string }) => void
  onClear: () => void
}) {
  const [rating, setRating] = React.useState<FeedbackRating>(initialRating)
  const [tags, setTags] = React.useState<string[]>([])
  const [comment, setComment] = React.useState("")

  // Reset state mỗi lần mở dialog cho một câu: ưu tiên feedback đã lưu
  // nếu cùng rating với nút vừa bấm, ngược lại bắt đầu form trống.
  React.useEffect(() => {
    if (!open) return
    if (existing && existing.rating === initialRating) {
      setRating(existing.rating)
      setTags(existing.tags ?? [])
      setComment(existing.comment ?? "")
    } else {
      setRating(initialRating)
      setTags([])
      setComment("")
    }
  }, [open, initialRating, existing, question?.question_id])

  const switchRating = (next: FeedbackRating) => {
    if (next === rating) return
    setRating(next)
    setTags([]) // từ vựng tag khác nhau giữa 👍 và 👎
  }

  const toggleTag = (id: string) =>
    setTags((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Phản hồi câu hỏi</DialogTitle>
          <DialogDescription>
            Phản hồi của bạn được dùng để sinh lại câu hỏi đúng ý hơn — câu bị 👎 sẽ
            được thay khi bấm &ldquo;Sinh lại theo phản hồi&rdquo;.
          </DialogDescription>
        </DialogHeader>

        {question && (
          <div className="max-h-24 overflow-y-auto rounded-md border bg-muted/40 p-3">
            <QuestionStem stem={question.stem} compact className="text-sm" />
          </div>
        )}

        <div className="flex flex-col gap-4">
          {/* Rating */}
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => switchRating("up")}
              className={cn(
                "flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition",
                rating === "up"
                  ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                  : "hover:bg-accent"
              )}
            >
              <ThumbsUpIcon className="size-4" />
              Thích — giữ câu này
            </button>
            <button
              type="button"
              onClick={() => switchRating("down")}
              className={cn(
                "flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition",
                rating === "down"
                  ? "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
                  : "hover:bg-accent"
              )}
            >
              <ThumbsDownIcon className="size-4" />
              Chê — sinh lại câu này
            </button>
          </div>

          {/* Tags */}
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              {rating === "down" ? "Vì sao chưa ổn?" : "Điểm bạn thích?"} (chọn được nhiều)
            </span>
            <div className="flex flex-wrap gap-1.5">
              {FEEDBACK_TAGS[rating].map((tag) => {
                const active = tags.includes(tag.id)
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => toggleTag(tag.id)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-xs transition",
                      active
                        ? rating === "down"
                          ? "border-rose-300 bg-rose-50 font-medium text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
                          : "border-emerald-300 bg-emerald-50 font-medium text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                        : "hover:bg-accent"
                    )}
                  >
                    {tag.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Comment */}
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              Mô tả thêm ý bạn muốn (tuỳ chọn)
            </span>
            <textarea
              value={comment}
              rows={3}
              maxLength={1000}
              placeholder={
                rating === "down"
                  ? "VD: Câu này chỉ thay số vào công thức, tôi muốn bài toán thực tế nhiều bước hơn"
                  : "VD: Tôi thích dạng bài gắn tình huống thực tế thế này, hãy tạo thêm"
              }
              onChange={(e) => setComment(e.target.value)}
              className="min-h-9 w-full resize-y rounded-md border bg-background px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <div>
            {existing && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                disabled={saving}
                onClick={onClear}
              >
                <Trash2Icon className="mr-1 size-3.5" />
                Xoá phản hồi
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
              Huỷ
            </Button>
            <Button
              type="button"
              disabled={saving}
              onClick={() => onSave({ rating, tags, comment: comment.trim() })}
            >
              {saving && <Loader2Icon className="mr-2 size-4 animate-spin" />}
              Lưu phản hồi
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
