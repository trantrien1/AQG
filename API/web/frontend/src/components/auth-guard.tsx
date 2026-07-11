"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { getToken } from "@/lib/api"

/** Chưa có token thì đá về /login; token hết hạn do api.ts xử lý khi gặp 401. */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = React.useState(false)

  React.useEffect(() => {
    if (getToken()) {
      setReady(true)
    } else {
      router.replace("/login")
    }
  }, [router])

  if (!ready) return null
  return <>{children}</>
}
