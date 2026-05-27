---
name: long-document-detection
description: Detect long or very long uploaded documents and decide whether to preprocess, warn, or require section selection before expensive MCQ generation. Use in IngestionAgent before LLM calls on large PDFs or text datasets.
---

# Long Document Detection

Prevent token blowups and quality drift caused by sending too much context into generation.

## Inputs
- Dataset units with `context`
- `long_doc_chars`
- `too_long_chars`

## Workflow
1. Count total characters, number of units, and max single-unit length.
2. Set `is_long` when total or single-unit length crosses `long_doc_chars`.
3. Set `is_too_long` when total length crosses `too_long_chars`.
4. For long documents, trigger preprocessing and summarize the steps taken.
5. For very long documents without a section filter, set `requires_user_selection`.

## Guardrails
- Do not silently process very large documents when the configured policy asks for user section selection.
- Keep warnings actionable: mention section filtering or explicit allow-very-long mode.

## Output
Return report fields:

```json
{
  "total_chars": 0,
  "num_units": 0,
  "max_unit_chars": 0,
  "is_long": false,
  "is_too_long": false,
  "requires_user_selection": false,
  "warning": null
}
```
