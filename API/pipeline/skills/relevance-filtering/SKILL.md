---
name: relevance-filtering
description: Rank and select the most useful context units for MCQ generation, especially for long documents. Use in IngestionAgent after knowledge extraction to avoid passing the whole document into planning and writing.
---

# Relevance Filtering

Choose a bounded, high-signal set of source units for generation.

## Inputs
- Preprocessed units with `summary`, `key_extracts`, `topic`, `pages`, and `context`
- Optional `section_filter`
- `max_units`

## Workflow
1. If `section_filter` matches units, prefer matching units.
2. Score units higher when they contain definitions, formulas, worked examples, exercises, solutions, or dense topic headings.
3. Penalize mostly-empty, duplicated, table-of-contents, reference, or formatting-only units.
4. Keep at most `max_units`.
5. Restore source order after ranking so citations remain easy to inspect.

## Guardrails
- Do not select only summaries; selected units must retain enough context for grounding.
- Do not remove all low-level prerequisite chunks if later chunks depend on them.
- Preserve pages and source IDs.

## Output
Return selected dataset units for blueprint planning and generation.
