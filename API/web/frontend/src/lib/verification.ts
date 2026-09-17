/**
 * Từ vựng trạng thái kiểm chứng, khớp với `pipeline/verification_status.py`.
 *
 * Vì sao không còn một nhãn "Verified" duy nhất: biểu thức kiểm chứng do chính
 * tác nhân viết đề sinh ra, nên nó khớp đáp án chỉ chứng minh câu hỏi NHẤT QUÁN
 * VỚI CHÍNH NÓ, không chứng minh đáp án đúng. Gắn nhãn "Verified" cho trường hợp
 * đó khiến người dùng tin vào một điều hệ thống chưa kiểm được.
 */
import type { Question } from "@/lib/api"

export type VerificationStatus =
  | "independently_verified"
  | "consistency_confirmed"
  | "mismatch"
  | "non_verifiable"
  | "refuted"

/**
 * Trạng thái của một câu hỏi. Bản ghi cũ (trước khi có `status`) được suy ra từ
 * cờ `verified` — và KHÔNG BAO GIỜ suy ra "đã kiểm chứng độc lập" từ cờ đó.
 */
export function verificationStatus(q: Question): VerificationStatus {
  const v = q.verification
  const known: VerificationStatus[] = [
    "independently_verified",
    "consistency_confirmed",
    "mismatch",
    "non_verifiable",
    "refuted",
  ]
  if (v?.status && known.includes(v.status as VerificationStatus)) {
    return v.status as VerificationStatus
  }
  if (!v?.engine || v.engine === "none") return "non_verifiable"
  if (v.verified === true) return "consistency_confirmed"
  if (v.verified === false) return "mismatch"
  return "non_verifiable"
}

/** Có được phép nói với người dùng là máy đã kiểm không. */
export function isMachineChecked(q: Question): boolean {
  const status = verificationStatus(q)
  return status === "independently_verified" || status === "consistency_confirmed"
}

/** Bằng chứng mạnh nhất: một nguồn tính toán độc lập cũng ra cùng đáp án. */
export function isIndependentlyVerified(q: Question): boolean {
  return verificationStatus(q) === "independently_verified"
}

/** Trạng thái buộc phải qua mắt người trước khi dùng. */
export function needsHumanReview(q: Question): boolean {
  const status = verificationStatus(q)
  return status === "mismatch" || status === "refuted"
}

/** Câu hỏi có thuộc dạng máy kiểm được không (tính toán vs khái niệm). */
export function isMachineVerifiable(q: Question): boolean {
  if (typeof q.verification?.machine_verifiable === "boolean") {
    return q.verification.machine_verifiable
  }
  const engine = q.verification?.engine
  return !!engine && engine !== "none"
}

export const STATUS_LABEL: Record<VerificationStatus, string> = {
  independently_verified: "Đã kiểm chứng độc lập",
  consistency_confirmed: "Nhất quán (chưa kiểm độc lập)",
  mismatch: "Lệch nguồn tính toán",
  non_verifiable: "Không kiểm được bằng máy",
  refuted: "Bị bác bỏ",
}

/** Câu giải thích đầy đủ — dùng cho tooltip/chi tiết, không rút gọn thành "đúng". */
export const STATUS_HELP: Record<VerificationStatus, string> = {
  independently_verified:
    "Một lời giải được dựng lại độc lập với lời giải gốc cho cùng đáp án, và CAS đã tính lại giá trị đó.",
  consistency_confirmed:
    "Biểu thức kiểm chứng khớp đáp án đã chọn, nhưng cả hai đều do cùng một tác nhân viết ra — đây là sự nhất quán, chưa phải bằng chứng đúng.",
  mismatch:
    "Các nguồn tính toán cho kết quả khác nhau. Chưa xác định được đáp án nào đúng — cần người kiểm.",
  non_verifiable:
    "Câu hỏi không thuộc dạng kiểm chứng được bằng máy (khái niệm, chứng minh, nhận định). Không có kết luận nào từ máy về tính đúng đắn.",
  refuted:
    "Tính toán độc lập cho kết quả khác đáp án đã chọn, hoặc có nhiều hơn một phương án đúng. Cần người kiểm.",
}

/** Màu badge theo trạng thái (Tailwind class). */
export const STATUS_BADGE_CLASS: Record<VerificationStatus, string> = {
  independently_verified:
    "border-emerald-300 text-emerald-700 dark:border-emerald-800 dark:text-emerald-300",
  consistency_confirmed:
    "border-sky-300 text-sky-700 dark:border-sky-800 dark:text-sky-300",
  mismatch:
    "border-amber-400/60 text-amber-700 dark:text-amber-400",
  non_verifiable:
    "border-muted-foreground/30 text-muted-foreground",
  refuted:
    "border-red-400 text-red-700 dark:text-red-400",
}
