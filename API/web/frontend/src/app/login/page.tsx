"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { BrainCircuitIcon, Loader2Icon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { getToken, login } from "@/lib/api"

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [error, setError] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)

  // Đã có token thì khỏi login lại (token hỏng sẽ bị 401 đẩy về đây sau).
  React.useEffect(() => {
    if (getToken()) router.replace("/upload")
  }, [router])

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError("")
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      router.replace("/upload")
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(
        message.includes("401")
          ? "Sai tên đăng nhập hoặc mật khẩu."
          : `Không đăng nhập được: ${message}`,
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BrainCircuitIcon className="size-5" />
          </div>
          <CardTitle>AQG — Toán</CardTitle>
          <CardDescription>Đăng nhập để sinh câu hỏi MCQ từ PDF</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Tên đăng nhập"
              autoComplete="username"
              autoFocus
              required
            />
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Mật khẩu"
              autoComplete="current-password"
              required
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2Icon className="size-4 animate-spin" />}
              Đăng nhập
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
