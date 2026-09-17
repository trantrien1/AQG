const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8080"

// ---- Auth: token lưu localStorage, gửi kèm mọi request qua Authorization ----

const TOKEN_KEY = "aqg_token"

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 401 từ backend = chưa đăng nhập / phiên hết hạn → về trang login. */
function handleUnauthorized(): never {
  clearToken()
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login"
  }
  throw new Error("401 Chưa đăng nhập")
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Accept": "application/json", ...authHeaders(), ...init?.headers },
  })
  if (res.status === 401 && !path.startsWith("/auth/")) handleUnauthorized()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export async function login(username: string, password: string): Promise<{ token: string; username: string }> {
  const data = await req<{ token: string; username: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    headers: { "Content-Type": "application/json" },
  })
  window.localStorage.setItem(TOKEN_KEY, data.token)
  return data
}

export async function logout(): Promise<void> {
  try {
    await req("/auth/logout", { method: "POST" })
  } catch {
    // DB/mạng lỗi thì vẫn xoá token phía client
  }
  clearToken()
}

export async function getMe(): Promise<{ username: string }> {
  return req("/auth/me")
}

/** Tải file qua fetch (link <a href> thường không gửi được header Authorization). */
async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) handleUnauthorized()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status} ${text}`)
  }
  const disposition = res.headers.get("content-disposition") ?? ""
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ---- Types ----

export interface JobMeta {
  job_id: string
  status: "pending" | "preparing" | "prepared" | "generating" | "running" | "done" | "error" | "cancelled"
  pdf_name?: string
  num_questions?: number
  created_at?: string
  error?: string
}

export interface OptionItem {
  key: "A" | "B" | "C" | "D"
  text: string
  error_type: string | null
}

export interface QualityTrait {
  rationale?: string
  score: number
}

export interface Question {
  question_id: string
  blueprint_slot_id?: string
  doc_id?: string
  subject?: string
  topic?: string
  kc_ids?: string[]
  cognitive_level?: string
  /** Mã các Chuẩn đầu ra (CĐR) mà câu hỏi được LLM gán sau khi sinh */
  learning_outcomes?: string[]
  difficulty_target?: number
  difficulty_estimated?: number
  difficulty_alignment?: boolean
  estimated_time_seconds?: number
  question_type?: string

  stem: string
  options: OptionItem[]
  answer_key: "A" | "B" | "C" | "D" | null

  explanation_correct?: string
  explanation_per_distractor?: Record<string, string>
  hint?: string | null

  // Smart-Study explanation block
  short_explanation?: string
  detailed_solution?: {
    steps?: Array<{ title: string; content: string }>
    final_answer?: string
  }
  why_correct?: string
  why_others_wrong?: Array<{ option: string; reason: string }>

  visual?: unknown

  source?: {
    doc_id?: string
    chunk_ids?: string[]
    pages?: number[]
    quote?: string
    quote_in_context?: boolean
  }

  verification?: {
    engine?: string
    method?: string
    /**
     * Cờ HẸP: biểu thức kiểm chứng do tác nhân viết đề khai có khớp đáp án hay
     * không. KHÔNG đọc là "đáp án đúng" — kết luận nằm ở `status`.
     */
    verified?: boolean | null
    /** independently_verified | consistency_confirmed | mismatch | non_verifiable | refuted */
    status?: string
    status_label_vi?: string
    status_label_en?: string
    machine_checked?: boolean
    machine_verifiable?: boolean
    question_kind?: "computational" | "conceptual"
    needs_human_review?: boolean
    evidence_sources?: string[]
    independent?: {
      attempted?: boolean
      definite?: boolean
      value?: number | null
      expression?: string
      source?: string
      detail?: string
      model?: string
    }
    verifier_version?: string
    numeric_crosscheck_points?: number
    detail?: string
    verified_at?: string
  }

  judging?: {
    grounding?: number
    quality?: number
    bloom_alignment?: number
    answer_prob?: number | null
    quality_traits?: Record<string, QualityTrait>
  }

  review?: {
    human_reviewed?: boolean
    status?: string
    reviewed_by?: string | null
    review_notes?: string | null
  }

  // Top-level review_status được /review endpoint set
  review_status: "pending_review" | "approved" | "rejected" | "needs_revision"
  reject_reason?: string
  reject_reason_code?: string
  reject_reason_stage?: string
  reject_log?: Array<RejectEntry | string>
  attempts?: number
  tags?: string[]
  version?: number
  _attempts?: number
}

export interface JobStatus {
  status: string
  mode?: string
  skill_mode?: string
  use_skills?: boolean
  progress?: number
  message?: string
  current_agent?: string
  accepted?: number
  target_accepted?: number
  rejected_count?: number
  partial?: boolean
  stopped_reason?: string | null
  cancelled?: boolean
  cancel_requested?: boolean
  reject_summary?: RejectSummary
  error?: string
}

export interface RejectEntry {
  reason_code?: string
  stage?: string
  attempt?: number
  message?: string
  score?: number | null
  action?: string
  slot_id?: string
}

export interface RejectSummary {
  reason_distribution?: Record<string, number>
  by_stage?: Record<string, number>
  recent?: Array<{
    slot_id?: string
    reason_code?: string
    message?: string
    attempts?: number
  }>
  top_failing_slots?: Array<{ slot_id: string; fails: number }>
  suggestions?: string[]
}

export interface RejectsResponse {
  summary: RejectSummary
  rejects: Array<{
    question_id?: string
    slot_id?: string
    topic?: string
    reject_reason?: string
    reject_reason_code?: string
    reject_reason_stage?: string
    reject_log?: Array<RejectEntry | string>
    attempts?: number
  }>
}

export interface CustomizationConfig {
  difficulty?: "easy" | "medium" | "hard" | "applied" | "applied_high" | "mixed"
  question_types?: string[]
  user_instruction?: string
  focus_topics?: string[]
  avoid_topics?: string[]
  style?: "default" | "similar_to_source_material" | "exam_style"
  requires_computation?: boolean
  requires_detailed_solution?: boolean
  strict_grounding?: boolean
  quick_prompts?: string[]
}

// ---- API calls ----

export interface LearningOutcomeInput {
  code?: string
  description: string
}

export async function uploadPDF(
  file: File,
  numQuestions: number,
  opts?: {
    directPdf?: boolean
    bloomLevel?: string
    difficulty?: string
    learningOutcomes?: LearningOutcomeInput[]
    /** false = bỏ lời giải/giải thích để sinh nhanh hơn (backend mặc định true). */
    includeExplanation?: boolean
  },
): Promise<{ job_id: string; direct_pdf?: boolean }> {
  const form = new FormData()
  form.append("file", file)
  form.append("num_questions", String(numQuestions))
  if (opts?.directPdf) form.append("direct_pdf", "1")
  if (opts?.includeExplanation === false) form.append("include_explanation", "0")
  if (opts?.bloomLevel) form.append("bloom_level", opts.bloomLevel)
  if (opts?.difficulty) form.append("difficulty", opts.difficulty)
  const outcomes = (opts?.learningOutcomes ?? []).filter((o) => o.description.trim())
  if (outcomes.length > 0) form.append("learning_outcomes", JSON.stringify(outcomes))
  return req<{ job_id: string; direct_pdf?: boolean }>("/upload", { method: "POST", body: form })
}

// ---- Two-step upload: /prepare ngay khi chọn file, /start khi bấm Generate ----

export interface PrepareOutline {
  document_title?: string
  topics?: string[]
  suggested_learning_outcomes?: LearningOutcomeInput[]
  suggested_num_questions?: number | null
}

export interface PrepareStatus {
  status: "none" | "preparing" | "ready" | "error"
  message?: string
  num_pages?: number
  attachments_ready?: boolean
  outline?: PrepareOutline | null
  error?: string
  error_code?: string
}

/** Bước 1: gọi ngay khi người dùng chọn xong file — backend render trang PDF
 * và trích dàn ý chủ đề chạy nền trong lúc người dùng còn đang chọn config. */
export async function preparePDF(file: File): Promise<{ job_id: string }> {
  const form = new FormData()
  form.append("file", file)
  return req<{ job_id: string }>("/prepare", { method: "POST", body: form })
}

export async function getPrepareStatus(jobId: string): Promise<PrepareStatus> {
  return req(`/job/${jobId}/prepare`)
}

/** Bước 2: gửi config và bắt đầu sinh — dùng lại trang PDF đã render ở /prepare. */
export async function startPreparedJob(
  jobId: string,
  numQuestions: number,
  opts?: {
    difficulty?: string
    bloomLevel?: string
    learningOutcomes?: LearningOutcomeInput[]
    /** false = bỏ lời giải/giải thích để sinh nhanh hơn (backend mặc định true). */
    includeExplanation?: boolean
  },
): Promise<{ ok: boolean; job_id: string }> {
  const form = new FormData()
  form.append("num_questions", String(numQuestions))
  if (opts?.difficulty) form.append("difficulty", opts.difficulty)
  if (opts?.bloomLevel) form.append("bloom_level", opts.bloomLevel)
  if (opts?.includeExplanation === false) form.append("include_explanation", "0")
  const outcomes = (opts?.learningOutcomes ?? []).filter((o) => o.description.trim())
  if (outcomes.length > 0) form.append("learning_outcomes", JSON.stringify(outcomes))
  return req(`/job/${jobId}/start`, { method: "POST", body: form })
}

/** Xoá job đã prepare khi người dùng bỏ/đổi file trước lúc Generate. */
export async function deleteJob(jobId: string): Promise<{ ok: boolean }> {
  return req(`/job/${jobId}`, { method: "DELETE" })
}

export interface JobConfig {
  mode?: string
  skill_mode?: string
  num_questions?: number
  bloom_level?: BloomLevel | "mixed"
  include_explanation?: boolean
  include_visuals?: boolean
  question_types?: string[]
  topic_filter?: string[]
  difficulty?: string
}

export type BloomLevel = "Nhận biết" | "Thông hiểu" | "Vận dụng" | "Vận dụng cao"

export async function configureJob(jobId: string, config: JobConfig): Promise<{ ok: boolean; config: JobConfig }> {
  const form = new FormData()
  const skillMode = config.skill_mode ?? config.mode ?? "Direct_PDF_Mode"
  form.append("mode", skillMode)
  form.append("skill_mode", skillMode)
  form.append("num_questions", String(config.num_questions ?? 12))
  form.append("bloom_level", config.bloom_level ?? "mixed")
  form.append("include_explanation", config.include_explanation ? "1" : "0")
  form.append("include_visuals", config.include_visuals ? "1" : "0")
  form.append("question_types", (config.question_types ?? []).join(","))
  form.append("topic_filter", (config.topic_filter ?? []).join(","))
  return req(`/job/${jobId}/configure`, { method: "POST", body: form })
}

export async function getJobConfig(jobId: string): Promise<{ config: JobConfig }> {
  return req(`/job/${jobId}/config`)
}

export async function startGenerate(
  jobId: string,
  opts: {
    numQuestions: number
    numSamples?: number
    useNli?: boolean
    bloomLevel?: BloomLevel | "mixed"
    mode?: string
    skillMode?: string
    difficulty?: string
  }
): Promise<{ ok: boolean }> {
  const form = new FormData()
  const skillMode = opts.skillMode ?? opts.mode ?? "Direct_PDF_Mode"
  form.append("mode", skillMode)
  form.append("skill_mode", skillMode)
  form.append("num_questions", String(opts.numQuestions))
  form.append("num_samples", String(opts.numSamples ?? 1))
  form.append("use_nli", opts.useNli ? "1" : "0")
  form.append("bloom_level", opts.bloomLevel ?? "mixed")
  if (opts.difficulty) form.append("difficulty", opts.difficulty)
  return req(`/job/${jobId}/generate`, { method: "POST", body: form })
}

export async function pollJobStatus(jobId: string): Promise<JobStatus> {
  return req(`/job/${jobId}/status`)
}

export async function getJobQuestions(jobId: string): Promise<{ questions: Question[]; rejected: Question[] }> {
  return req(`/job/${jobId}/questions`)
}

// ---- Question feedback (RLHF-style) ----

export type FeedbackRating = "up" | "down"

export interface QuestionFeedback {
  question_id: string
  rating: FeedbackRating
  tags: string[]
  comment: string
  stem?: string
  cognitive_level?: string
  created_at?: string
}

export async function getJobFeedback(jobId: string): Promise<{ feedback: QuestionFeedback[] }> {
  return req(`/job/${jobId}/feedback`)
}

/** rating=null xoá feedback của câu đó. */
export async function submitQuestionFeedback(
  jobId: string,
  payload: { question_id: string; rating: FeedbackRating | null; tags?: string[]; comment?: string },
): Promise<{ ok: boolean; feedback: QuestionFeedback[] }> {
  return req(`/job/${jobId}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  })
}

/** Giữ các câu không bị chê, sinh lại các câu 👎 theo hồ sơ sở thích. */
export async function regenerateFromFeedback(
  jobId: string,
): Promise<{ ok: boolean; keeping: number; replacing: number }> {
  return req(`/job/${jobId}/generate-from-feedback`, { method: "POST" })
}

/** Sinh thêm câu mới từ cùng PDF, giữ nguyên câu hiện có + feedback đã học. */
export async function generateMoreQuestions(
  jobId: string,
  count: number,
): Promise<{ ok: boolean; adding: number; current: number }> {
  const form = new FormData()
  form.append("num_questions", String(count))
  return req(`/job/${jobId}/generate-more`, { method: "POST", body: form })
}

export async function reviewQuestion(jobId: string, questionId: string, action: "approve" | "reject"): Promise<{ ok: boolean }> {
  const form = new FormData()
  form.append("question_id", questionId)
  form.append("action", action)
  return req(`/job/${jobId}/review`, { method: "POST", body: form })
}

export async function listJobs(): Promise<{ jobs: JobMeta[] }> {
  return req("/jobs")
}

export function downloadJobExport(jobId: string): Promise<void> {
  return downloadFile(`/job/${jobId}/export`, `${jobId}.json`)
}

// ---- Cancel + customization + rejects ----

export async function cancelJob(jobId: string): Promise<{ ok: boolean; reason?: string; status?: string }> {
  return req(`/job/${jobId}/cancel`, { method: "POST" })
}

export async function customizeJob(
  jobId: string,
  payload: CustomizationConfig,
): Promise<{ ok: boolean; config: CustomizationConfig; generation_config: CustomizationConfig }> {
  return req(`/job/${jobId}/customize`, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  })
}

export async function getJobRejects(jobId: string): Promise<RejectsResponse> {
  return req(`/job/${jobId}/rejects`)
}

// ---- Smart Practice ----

export interface PracticeQuestion {
  question_id: string
  topic?: string
  cognitive_level?: string
  question_type?: string
  stem: string
  options: Array<{ key: string; text: string }>
  visual?: unknown
  hint?: string | null
}

export interface PracticeSessionStats {
  answered: number
  correct: number
  streak: number
  by_topic: Record<string, { answered: number; correct: number }>
}

export interface PracticeSession {
  session_id: string
  created_at?: string
  current_question_id: string | null
  served: string[]
  history: Array<{
    question_id: string
    topic?: string
    skill?: string | null
    difficulty?: string
    answer_chosen?: string
    correct_key?: string
    is_correct: boolean
    feedback?: "like" | "dislike" | null
    answered_at?: string
  }>
  stats: PracticeSessionStats
}

export interface PracticeAnswerVerdict {
  is_correct: boolean
  correct_key: string
  explanation: {
    why_correct?: string
    detailed_solution?: { steps?: Array<{ title: string; content: string }>; final_answer?: string }
    why_others_wrong?: Array<{ option: string; reason: string }>
  }
  session_stats: PracticeSessionStats
}

export async function startPractice(jobId: string): Promise<{ session: PracticeSession; question: PracticeQuestion | null }> {
  return req(`/job/${jobId}/practice/start`, { method: "POST" })
}

export async function getPracticeSession(jobId: string, sessionId: string): Promise<{ session: PracticeSession; question: PracticeQuestion | null }> {
  return req(`/job/${jobId}/practice/${sessionId}`)
}

export async function listPracticeSessions(jobId: string): Promise<{ sessions: Array<{ session_id: string; created_at?: string; answered?: number; correct?: number }> }> {
  return req(`/job/${jobId}/practice`)
}

export async function answerPracticeQuestion(jobId: string, sessionId: string, questionId: string, answerKey: string): Promise<PracticeAnswerVerdict> {
  return req(`/job/${jobId}/practice/${sessionId}/answer`, {
    method: "POST",
    body: JSON.stringify({ question_id: questionId, answer_key: answerKey }),
    headers: { "Content-Type": "application/json" },
  })
}

export async function submitPracticeFeedback(jobId: string, sessionId: string, questionId: string, feedback: "like" | "dislike"): Promise<{ ok: boolean }> {
  return req(`/job/${jobId}/practice/${sessionId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ question_id: questionId, feedback }),
    headers: { "Content-Type": "application/json" },
  })
}

export async function nextPracticeQuestion(jobId: string, sessionId: string): Promise<{ question: PracticeQuestion | null; finished: boolean }> {
  return req(`/job/${jobId}/practice/${sessionId}/next`, { method: "POST" })
}

// ---- Benchmark ----

export interface BenchmarkMetrics {
  job_id?: string
  accepted_count: number
  rejected_count: number
  total_attempted: number
  acceptance_rate: number
  avg_attempts_per_accepted?: number | null
  reject_reason_distribution: Record<string, number>
  verifier_pass_rate: number
  fast_accept_rate: number
  grounding_avg?: number | null
  quote_score_avg?: number | null
  quality_avg?: number | null
  duplicate_rate: number
  explanation_quality_avg?: number | null
  user_instruction_alignment_avg?: number | null
  stopped_reason?: string | null
  cost_total_tokens?: number | null
  cost_total_calls?: number | null
}

export async function getJobBenchmark(jobId: string): Promise<{ metrics: BenchmarkMetrics }> {
  return req(`/job/${jobId}/benchmark`)
}

// ---- Local Question Banks ----

export interface QuestionBank {
  bank_id: string
  name: string
  description?: string
  created_at?: string
  updated_at?: string
  question_count?: number
}

export interface BankQuestion {
  bank_question_id: string
  bank_id: string
  original_question_id?: string
  source_job_id?: string
  source_pdf_name?: string
  created_at?: string
  updated_at?: string
  question: Question
}

export interface DuplicateReason {
  type: "exact_stem" | "near_stem" | "same_answer_similar_stem" | "same_source_pages" | "semantic"
  score: number
}

export interface DuplicateMatch {
  bank_question_id: string
  original_question_id?: string
  stem?: string
  answer_key?: string
  reasons: DuplicateReason[]
  max_score: number
}

export interface DuplicateCheckItem {
  question_id?: string
  stem?: string
  duplicates: DuplicateMatch[]
}

export interface DuplicateCheckResponse {
  results: DuplicateCheckItem[]
  semantic_enabled: boolean
  embedding_errors?: string[]
}

export interface AddToBankResponse {
  added: Array<{ bank_question_id: string; question_id?: string; stem?: string; duplicates: DuplicateMatch[] }>
  skipped: Array<{ question_id?: string; stem?: string; duplicates: DuplicateMatch[] }>
  replaced: DuplicateMatch[]
  semantic_enabled: boolean
  embedding_errors?: string[]
}

export async function listBanks(): Promise<{ banks: QuestionBank[] }> {
  return req("/banks")
}

export async function createBank(name: string, description = ""): Promise<{ bank: QuestionBank }> {
  return req("/banks", {
    method: "POST",
    body: JSON.stringify({ name, description }),
    headers: { "Content-Type": "application/json" },
  })
}

export async function getBank(bankId: string): Promise<{ bank: QuestionBank; questions: BankQuestion[] }> {
  return req(`/bank/${bankId}`)
}

export async function checkBankDuplicates(bankId: string, questions: Question[]): Promise<DuplicateCheckResponse> {
  return req(`/bank/${bankId}/duplicates`, {
    method: "POST",
    body: JSON.stringify({ questions }),
    headers: { "Content-Type": "application/json" },
  })
}

export async function addQuestionsToBank(
  bankId: string,
  payload: {
    questions: Question[]
    sourceJobId?: string
    sourcePdfName?: string
    duplicateAction?: "skip" | "replace" | "force"
  },
): Promise<AddToBankResponse> {
  return req(`/bank/${bankId}/questions`, {
    method: "POST",
    body: JSON.stringify({
      questions: payload.questions,
      source_job_id: payload.sourceJobId,
      source_pdf_name: payload.sourcePdfName,
      duplicate_action: payload.duplicateAction ?? "skip",
    }),
    headers: { "Content-Type": "application/json" },
  })
}

export async function deleteBankQuestion(bankId: string, bankQuestionId: string): Promise<{ ok: boolean }> {
  return req(`/bank/${bankId}/questions/${bankQuestionId}`, { method: "DELETE" })
}

export function downloadBankExport(bankId: string, format: "json" | "xlsx" | "docx"): Promise<void> {
  return downloadFile(`/bank/${bankId}/export?format=${format}`, `bank-${bankId}.${format}`)
}
