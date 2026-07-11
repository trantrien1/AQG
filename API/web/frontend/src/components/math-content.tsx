"use client"

/**
 * MathContent — render hỗn hợp text, markdown, LaTeX và code block.
 *
 * Chiến lược:
 * 1. Bảo vệ các đoạn math (`$...$`, `$$...$$`, `\(...\)`, `\[...\]`) khỏi marked
 *    bằng cách thay thế tạm thời bằng placeholder.
 * 2. Cho `marked` render phần còn lại (markdown → HTML).
 * 3. Render từng segment: HTML | math (qua KaTeX `renderToString`).
 * 4. Code block đã được marked render thành `<pre><code>...</code></pre>` —
 *    áp style cơ bản qua CSS class.
 *
 * Lưu ý an toàn: input chỉ là text từ LLM/server đã được pipeline kiểm soát.
 * Marked được cấu hình với `breaks: true`, `gfm: true`. Không cho phép HTML thô.
 */

import * as React from "react"
import { marked } from "marked"
import katex from "katex"
import "katex/dist/katex.min.css"
import { cn } from "@/lib/utils"

// Configure marked globally (idempotent).
marked.setOptions({
  gfm: true,
  breaks: true,
})

interface MathSegment {
  type: "math" | "html"
  content: string
  display?: boolean
}

const MATH_PATTERNS: { regex: RegExp; display: boolean }[] = [
  // Display math first (longer): $$...$$, \[...\]
  { regex: /\$\$([\s\S]+?)\$\$/g, display: true },
  { regex: /\\\[([\s\S]+?)\\\]/g, display: true },
  // Inline: $...$, \(...\)
  // Avoid currency/false-positive: require non-space immediately after $.
  { regex: /(?<![\\$])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\d)/g, display: false },
  { regex: /\\\(([\s\S]+?)\\\)/g, display: false },
]

const BARE_LATEX_PATTERNS: RegExp[] = [
  /\\frac\s*\{[^{}]+?\}\s*\{[^{}]+?\}(?:\s*=\s*[-+]?\d+(?:[.,]\d+)?)?/g,
  /\\sqrt\s*\{[^{}]+?\}(?:\s*=\s*[-+]?\d+(?:[.,]\d+)?)?/g,
  /\\binom\s*\{[^{}]+?\}\s*\{[^{}]+?\}(?:\s*=\s*[-+]?\d+(?:[.,]\d+)?)?/g,
  /\\int\b[^,.;:\n]+?d[A-Za-z]/g,
]

function mathPlaceholder(index: number): string {
  // Avoid `_` because Markdown treats __...__ as emphasis and corrupts tokens
  // before we can restore the KaTeX HTML.
  return `@@AQGMATH${index}@@`
}

function renderMathSafe(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, {
      displayMode: display,
      throwOnError: false,
      strict: "ignore",
      output: "html",
      trust: false,
    })
  } catch {
    return `<code class="text-destructive">${escapeHtml(tex)}</code>`
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
}

function latexifyLegacyExpr(expr: string): string {
  return expr
    .replace(/\*\*/g, "^")
    .replace(
      /\bbinomial\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)/g,
      "\\binom{$1}{$2}"
    )
    .replace(
      /\bC\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)/g,
      "\\binom{$1}{$2}"
    )
    .replace(/\bsqrt\s*\(\s*([^()]+?)\s*\)/g, "\\sqrt{$1}")
    .replace(/\bfactorial\s*\(\s*([^()]+?)\s*\)/g, "$1!")
    .replace(/(?<=[\w}\]])\s*\*\s*(?=[\w{(\\])/g, " \\cdot ")
}

function repairMathInner(tex: string): string {
  return tex
    .replace(/\\[()\[\]]|\$\$?/g, "")
    .replace(/\\,\s*(d[A-Za-z])/g, "\\,$1")
}

function repairNestedMathDelimiters(input: string): string {
  return input
    .replace(/\\\[([\s\S]+?)\\\]/g, (_match, tex) => `\\[${repairMathInner(tex)}\\]`)
    .replace(/\$\$([\s\S]+?)\$\$/g, (_match, tex) => `$$${repairMathInner(tex)}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_match, tex) => `\\(${repairMathInner(tex)}\\)`)
}

function looksLikeStandaloneMath(text: string): boolean {
  const s = text.trim()
  if (!s || s.length > 180) return false
  if (/[À-ỹĐđ]/.test(s)) return false
  if (/^[-+−]?\d+(?:[.,]\d+)?$/.test(s)) return false
  if (!/(?:\*\*|\^|[=<>≤≥√∫∑]|[A-Za-z0-9]\s*[+\-*/]\s*[A-Za-z0-9])/.test(s)) {
    return false
  }
  const words = s.match(/[A-Za-z]{2,}/g) ?? []
  const mathWords = new Set([
    "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "sqrt",
    "binomial", "frac", "int", "lim", "dx", "dy", "dt",
  ])
  return words.every((w) => mathWords.has(w.toLowerCase()))
}

function normalizeLegacyMathText(input: string): string {
  let working = input.replace(/\*\*/g, "^")

  const stash: string[] = []
  const put = (expr: string) => {
    const id = `__AUTO_MATH_${stash.length}__`
    stash.push(`\\(${latexifyLegacyExpr(expr)}\\)`)
    return id
  }

  for (const pattern of BARE_LATEX_PATTERNS) {
    working = working.replace(pattern, (match) => put(match))
  }

  const legacyPatterns = [
    /\bsqrt\s*\(\s*[^()]+?\s*\)(?:\s*=\s*[-+]?\d+(?:[.,]\d+)?)?/g,
    /\bbinomial\s*\(\s*[^,()]+?\s*,\s*[^()]+?\s*\)(?:\s*=\s*[-+]?\d+(?:[.,]\d+)?)?/g,
    /\bC\s*\(\s*[^,()]+?\s*,\s*[^()]+?\s*\)(?:\s*=\s*[-+]?\d+(?:[.,]\d+)?)?/g,
  ]
  for (const pattern of legacyPatterns) {
    working = working.replace(pattern, (match) => put(match))
  }

  working = working.replace(
    /(?<![\w\\])([A-Za-z0-9]\w*(?:\^\{?[-+]?\w+\}?)?(?:\s*[+\-]\s*(?:\d+(?:[.,]\d+)?|[A-Za-z]\w*(?:\^\{?[-+]?\w+\}?)?))*\s*=\s*[-+]?\d+(?:[.,]\d+)?)/g,
    (match) => put(match)
  )
  working = working.replace(
    /(?<![\w\\])([A-Za-z0-9]\w*\^\{?[-+]?\w+\}?(?:\s*[+\-]\s*\d+)?)/g,
    (match) => put(match)
  )

  if (stash.length === 0 && looksLikeStandaloneMath(working)) {
    return `\\(${latexifyLegacyExpr(working)}\\)`
  }

  stash.forEach((value, index) => {
    working = working.split(`__AUTO_MATH_${index}__`).join(value)
  })
  return working
}

/**
 * Tách input thành các segment {math, html} theo thứ tự xuất hiện.
 */
function parseSegments(input: string, inline = false): MathSegment[] {
  if (!input) return []

  // Bước 1: extract math, replace bằng placeholder để marked không đụng tới.
  const placeholders: { id: string; html: string }[] = []
  let working = repairNestedMathDelimiters(input)
  let counter = 0

  for (const { regex, display } of MATH_PATTERNS) {
    working = working.replace(regex, (_match, tex) => {
      const id = mathPlaceholder(counter++)
      placeholders.push({
        id,
        html: renderMathSafe(repairMathInner(String(tex).trim()), display),
      })
      return id
    })
  }

  // Dữ liệu cũ hoặc model lệch format có thể còn `\frac{...}{...}`,
  // `sqrt(x)`, `x**2` chưa bọc delimiter. Bọc nhẹ để KaTeX vẫn render đẹp.
  working = normalizeLegacyMathText(working)

  // Bước 2: cho marked parse phần còn lại.
  const renderedHtml = (
    inline ? marked.parseInline(working) : marked.parse(working)
  ) as string

  // Bước 3: replace placeholder lại.
  let final = renderedHtml
  for (const p of placeholders) {
    // KaTeX HTML có thể chứa $, ngoặc nhọn... → dùng split/join cho an toàn.
    final = final.split(p.id).join(p.html)
  }

  return [{ type: "html", content: final }]
}

interface MathContentProps {
  text?: string | null
  className?: string
  /** Inline (span) thay vì block (div). Mặc định block. */
  inline?: boolean
  /** Cho phép xuống dòng giữ nguyên với pre-wrap nếu input không có markdown. */
  preserveWhitespace?: boolean
}

/**
 * Render hỗn hợp markdown + LaTeX + code block.
 *
 * Use cases:
 * - Câu hỏi sinh từ LLM có thể chứa: `\frac{a}{b}`, `**bold**`, code block, list...
 * - Pipeline Generator/Verifier đôi khi mix natural notation và LaTeX.
 *
 * Component cố gắng "best-effort": dù input chỉ là plain text, vẫn render OK.
 */
export function MathContent({
  text,
  className,
  inline = false,
  preserveWhitespace = false,
}: MathContentProps) {
  const html = React.useMemo(() => {
    if (!text) return ""
    const segments = parseSegments(text, inline)
    return segments.map((s) => s.content).join("")
  }, [text, inline])

  if (!text) {
    return null
  }

  // Plain text fallback: nếu input không có dấu markdown nào, render như text
  // (tránh wrap thừa thẻ <p> từ marked làm mất responsive).
  const looksLikeMarkdown =
    /[*_`#~\[\]\\$|>-]/.test(text) || /\n\s*\n/.test(text)

  if (!looksLikeMarkdown && !inline) {
    return (
      <div
        className={cn(
          "prose-mcq",
          preserveWhitespace && "whitespace-pre-wrap",
          className
        )}
      >
        {text}
      </div>
    )
  }

  const Tag = inline ? "span" : "div"
  return (
    <Tag
      className={cn("prose-mcq", className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export default MathContent
