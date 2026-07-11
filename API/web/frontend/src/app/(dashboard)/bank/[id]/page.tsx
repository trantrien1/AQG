"use client"

import * as React from "react"
import { useParams } from "next/navigation"
import { DownloadIcon, Loader2Icon, Trash2Icon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { QuestionStem } from "@/components/question/question-stem"
import {
  deleteBankQuestion,
  downloadBankExport,
  getBank,
  type BankQuestion,
  type QuestionBank,
} from "@/lib/api"

export default function BankDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [bank, setBank] = React.useState<QuestionBank | null>(null)
  const [questions, setQuestions] = React.useState<BankQuestion[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState("")
  const [search, setSearch] = React.useState("")

  React.useEffect(() => {
    getBank(id)
      .then((data) => {
        setBank(data.bank)
        setQuestions(data.questions ?? [])
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return questions
    return questions.filter((item) => {
      const q = item.question
      return [q.stem, q.topic, q.cognitive_level, q.question_id]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    })
  }, [questions, search])

  const remove = async (bankQuestionId: string) => {
    await deleteBankQuestion(id, bankQuestionId)
    setQuestions((prev) => prev.filter((item) => item.bank_question_id !== bankQuestionId))
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Loader2Icon className="size-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{bank?.name ?? "Question Bank"}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{questions.length} questions</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(["xlsx", "docx", "json"] as const).map((format) => (
            <button
              key={format}
              type="button"
              onClick={() => downloadBankExport(id, format).catch((err: Error) => setError(err.message))}
              className="inline-flex h-8 items-center gap-2 rounded-md border bg-background px-3 text-sm font-medium hover:bg-muted"
            >
              <DownloadIcon className="size-4" />
              {format.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search questions"
        className="max-w-xl"
      />

      {filtered.length === 0 ? (
        <div className="flex min-h-80 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
          No questions found.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b bg-muted/60 text-xs text-muted-foreground">
              <tr>
                <th className="w-14 px-3 py-2 text-left font-medium">#</th>
                <th className="px-3 py-2 text-left font-medium">Question</th>
                <th className="w-40 px-3 py-2 text-left font-medium">Bloom</th>
                <th className="w-44 px-3 py-2 text-left font-medium">Source</th>
                <th className="w-20 px-3 py-2 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, idx) => (
                <tr key={item.bank_question_id} className="border-b last:border-b-0 hover:bg-muted/40">
                  <td className="px-3 py-3 text-xs text-muted-foreground">{idx + 1}</td>
                  <td className="px-3 py-3">
                    <QuestionStem stem={item.question.stem} compact truncated />
                    <div className="mt-1 text-[11px] text-muted-foreground">{item.question.question_id}</div>
                  </td>
                  <td className="px-3 py-3">
                    <Badge variant="outline">{item.question.cognitive_level ?? "n/a"}</Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground">
                    <span className="line-clamp-2">{item.source_pdf_name || item.source_job_id || "local"}</span>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <Button
                      variant="outline"
                      size="icon-sm"
                      className="text-destructive"
                      onClick={() => remove(item.bank_question_id)}
                    >
                      <Trash2Icon className="size-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
