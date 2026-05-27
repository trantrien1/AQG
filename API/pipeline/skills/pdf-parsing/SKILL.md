---
name: pdf-parsing
description: Parse uploaded PDFs into text-bearing dataset units while preserving page references and source metadata. Use at the start of IngestionAgent before long-document detection, chunking, cleanup, and MCQ generation.
---

# PDF Parsing

Convert a PDF into structured source units that later agents can cite.

## Inputs
- `pdf_path`
- chunking options such as `target_chars`, `chunk_page_threshold`, and `force_chunk`
- low-quality filtering flag

## Workflow
1. Extract text per page and keep page numbers.
2. Remove repeated headers, footers, page numbers, and obvious boilerplate.
3. Repair known Vietnamese extraction artifacts when safe, including legacy glyph issues such as `ƣ` to `ư`.
4. Detect headings when possible and use them as topic hints.
5. Respect page-threshold and force-chunk settings: keep small PDFs whole when configured, chunk larger PDFs by heading/page/context size.
6. Apply low-quality filtering for table-of-contents, code-only, or near-empty chunks, while preserving math-heavy educational chunks.
7. Build dataset units with stable `doc_id`, `topic`, `pages`, and `context`.
8. Preserve source filename and PDF parsing metadata under `metadata`.

## Guardrails
- Do not invent missing text or formulas.
- Prefer keeping a noisy educational passage over deleting a possible definition, example, exercise, table explanation, or formula.
- Keep page references even when text extraction is imperfect.
- Do not strip symbol-heavy lines only because they are short; they may be formulas.

## Output
Return the pipeline dataset shape:

```json
{
  "metadata": {"source": "...", "parsed_from_pdf": true},
  "pdf_000": {"topic": "...", "pages": [1], "context": "..."}
}
```
