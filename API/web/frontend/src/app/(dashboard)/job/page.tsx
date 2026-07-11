import { redirect } from "next/navigation"

// /job không có trang danh sách riêng — dùng chung trang /jobs.
export default function JobRootPage() {
  redirect("/jobs")
}
