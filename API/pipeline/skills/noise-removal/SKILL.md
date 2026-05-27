---
name: noise-removal
description: Remove obvious extraction noise from parsed PDF text before chunk selection, summarization, retrieval, or MCQ generation. Use in IngestionAgent on raw or parsed document text.
---

# Noise Removal

Clean text while preserving educational evidence.

## Workflow
1. Remove standalone page numbers, repeated headers, repeated footers, and dot-leader table-of-contents lines.
2. Remove references or index-like blocks only when they are not the requested content.
3. Normalize repeated whitespace and blank lines.
4. Keep mathematical definitions, examples, exercises, diagrams captions, formulas, and answer-bearing text.
5. Return text with enough original phrasing for source quote matching.

## Guardrails
- Do not paraphrase source content.
- Do not delete formulas just because they are short or symbol-heavy.
- Do not collapse text so aggressively that quote offsets or page traceability become useless.

## Output
Return cleaned text.
