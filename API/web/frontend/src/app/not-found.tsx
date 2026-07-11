import Link from "next/link"
import { BrainCircuitIcon } from "lucide-react"

export default function NotFound() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-background p-4 text-center">
      <div className="flex size-16 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
        <BrainCircuitIcon className="size-8" />
      </div>
      <div className="space-y-2">
        <h1 className="text-4xl font-bold tabular-nums">404</h1>
        <p className="text-muted-foreground">Trang này không tồn tại.</p>
      </div>
      <Link
        href="/upload"
        className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Về trang Upload
      </Link>
    </div>
  )
}
