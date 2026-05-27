---
name: chunking
description: Split long learning documents into generation-safe context units while preserving headings, pages, definitions, formulas, examples, and exercises. Use in IngestionAgent after parsing and noise removal.
---

# Chunking

Break long source text into stable units that can be summarized, ranked, and cited.

## Inputs
- Dataset units with `topic`, `pages`, and `context`
- `target_chars`
- `max_chars`

## Workflow
1. Prefer section, chapter, lesson, or heading boundaries.
2. Otherwise group paragraphs near `target_chars`.
3. Avoid cutting through a definition, theorem, formula block, worked example, exercise, or solution.
4. Keep pages, `source_doc_id`, `part_index`, and topic hints.
5. Drop units that are too short to support a grounded question unless they contain a clear formula or definition.

## Guardrails
- Do not merge unrelated sections just to hit a target length.
- Do not exceed `max_chars` unless a single atomic block is longer.
- Preserve source order for later traceability.

## Output
Return units shaped like:

```json
{
  "doc_id": "prep_0000",
  "source_doc_id": "pdf_000",
  "part_index": 0,
  "topic": "...",
  "pages": [],
  "context": "..."
}
```
