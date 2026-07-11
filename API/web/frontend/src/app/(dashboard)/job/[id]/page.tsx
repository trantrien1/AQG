"use client"

import { useEffect } from "react"
import { useParams, useRouter } from "next/navigation"
import { Loader2Icon } from "lucide-react"
import { pollJobStatus } from "@/lib/api"

// /job/{id} không có UI riêng (breadcrumb và link tay có thể trỏ vào đây):
// job xong thì về trang câu hỏi, còn lại về trang sinh câu hỏi.
export default function JobIndexPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  useEffect(() => {
    let cancelled = false
    pollJobStatus(id)
      .then((s) => {
        if (cancelled) return
        router.replace(s.status === "done" ? `/job/${id}/questions` : `/job/${id}/generate`)
      })
      .catch(() => {
        if (!cancelled) router.replace("/jobs")
      })
    return () => {
      cancelled = true
    }
  }, [id, router])

  return (
    <div className="flex flex-1 items-center justify-center py-24 text-muted-foreground">
      <Loader2Icon className="mr-2 size-4 animate-spin" />
      Đang mở job…
    </div>
  )
}
