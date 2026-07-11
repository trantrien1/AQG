"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { NavMain } from "@/components/nav-main"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
} from "@/components/ui/sidebar"
import {
  UploadIcon,
  BrainCircuitIcon,
  ZapIcon,
  ClipboardListIcon,
  HistoryIcon,
  CheckCircleIcon,
  LibraryIcon,
  LogOutIcon,
} from "lucide-react"
import { getMe, logout, pollJobStatus, type JobStatus } from "@/lib/api"

const navStart = [
  { title: "Banks", url: "/banks", icon: <LibraryIcon /> },
  { title: "Tải lên PDF", url: "/upload", icon: <UploadIcon /> },
  { title: "Lịch sử Jobs", url: "/jobs", icon: <HistoryIcon /> },
]

// Map job status to completed steps
function getCompletedSteps(status: string | undefined): Set<string> {
  const steps = new Set<string>()
  if (!status) return steps
  if (["generating", "running", "done"].includes(status)) steps.add("generate")
  if (status === "done") steps.add("questions")
  return steps
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()
  const jobMatch = pathname.match(/^\/job\/([^/]+)/)
  const currentJobId = jobMatch?.[1] ?? null
  const [jobStatus, setJobStatus] = React.useState<string | undefined>()
  const [username, setUsername] = React.useState("")

  React.useEffect(() => {
    getMe().then((me) => setUsername(me.username)).catch(() => {})
  }, [])

  const handleLogout = async () => {
    await logout()
    window.location.href = "/login"
  }

  React.useEffect(() => {
    if (!currentJobId) return
    pollJobStatus(currentJobId).then((s: JobStatus) => setJobStatus(s.status)).catch(() => {})
  }, [currentJobId, pathname])

  const completed = getCompletedSteps(jobStatus)

  const jobSteps = currentJobId
    ? [
        { title: "Sinh câu hỏi", url: `/job/${currentJobId}/generate`, icon: <ZapIcon />, step: "generate" },
        { title: "Xem câu hỏi", url: `/job/${currentJobId}/questions`, icon: <ClipboardListIcon />, step: "questions" },
      ]
    : []

  return (
    <Sidebar variant="inset" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link href="/upload" />}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <BrainCircuitIcon className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold">AQG — Toán</span>
                <span className="truncate text-xs text-muted-foreground">MCQ Generator</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={navStart} label="Bắt đầu" />
        {currentJobId && (
          <SidebarGroup>
            <SidebarGroupLabel className="truncate text-xs">
              Job: {currentJobId.slice(0, 8)}…
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {jobSteps.map((item) => (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      isActive={pathname === item.url}
                      tooltip={item.title}
                      render={<Link href={item.url} />}
                    >
                      {completed.has(item.step)
                        ? <CheckCircleIcon className="size-4 text-green-500" />
                        : item.icon}
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={handleLogout} tooltip="Đăng xuất">
              <LogOutIcon className="size-4" />
              <span className="truncate">
                Đăng xuất{username ? ` (${username})` : ""}
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
