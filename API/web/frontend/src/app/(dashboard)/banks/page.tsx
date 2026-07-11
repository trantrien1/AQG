"use client"

import * as React from "react"
import Link from "next/link"
import { Loader2Icon, PlusIcon, LibraryIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { listBanks, createBank, type QuestionBank } from "@/lib/api"

export default function BanksPage() {
  const [banks, setBanks] = React.useState<QuestionBank[]>([])
  const [loading, setLoading] = React.useState(true)
  const [creating, setCreating] = React.useState(false)
  const [name, setName] = React.useState("")
  const [error, setError] = React.useState("")

  React.useEffect(() => {
    listBanks()
      .then((data) => setBanks(data.banks ?? []))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    setError("")
    try {
      const { bank } = await createBank(name.trim())
      setBanks((prev) => [bank, ...prev])
      setName("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed")
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Question Banks</h1>
          <p className="mt-1 text-sm text-muted-foreground">{banks.length} banks</p>
        </div>
        <form onSubmit={handleCreate} className="flex w-full gap-2 sm:w-auto">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="New bank name"
            className="min-w-0 sm:w-64"
          />
          <Button type="submit" disabled={creating || !name.trim()}>
            {creating ? <Loader2Icon className="mr-2 size-4 animate-spin" /> : <PlusIcon className="mr-2 size-4" />}
            Create
          </Button>
        </form>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <div className="flex flex-1 items-center justify-center p-10">
          <Loader2Icon className="size-8 animate-spin text-muted-foreground" />
        </div>
      ) : banks.length === 0 ? (
        <div className="flex min-h-80 flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center">
          <LibraryIcon className="size-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No banks yet.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/60 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Name</th>
                <th className="w-32 px-3 py-2 text-left font-medium">Questions</th>
                <th className="w-48 px-3 py-2 text-left font-medium">Updated</th>
                <th className="w-24 px-3 py-2 text-right font-medium">Open</th>
              </tr>
            </thead>
            <tbody>
              {banks.map((bank) => (
                <tr key={bank.bank_id} className="border-b last:border-b-0 hover:bg-muted/40">
                  <td className="px-3 py-3 font-medium">{bank.name}</td>
                  <td className="px-3 py-3 text-muted-foreground">{bank.question_count ?? 0}</td>
                  <td className="px-3 py-3 text-xs text-muted-foreground">{bank.updated_at ?? ""}</td>
                  <td className="px-3 py-3 text-right">
                    <Button size="sm" variant="outline" render={<Link href={`/bank/${bank.bank_id}`} />}>
                      Open
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
