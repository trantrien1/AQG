---
name: duplicate-detection
description: Detect duplicate and near-duplicate MCQ candidates across accepted questions using normalized stems, answers, source quotes, and option patterns. Use in VerifierAgent and OrchestratorAgent before accepting a generated question.
---

# Duplicate Detection

Prevent the bank from accumulating repeated items.

## Workflow
1. Normalize whitespace, casing, punctuation, math display variants, stems, answers, and source quotes.
2. Compare stem similarity with token overlap and sequence similarity.
3. Treat same answer plus same or highly similar source quote as a strong duplicate signal.
4. Compare option patterns when stems differ but the item tests the same surface calculation.
5. Return a reject reason that identifies the duplicate dimension.

## Guardrails
- Do not reject distinct applications that share the same formula but use different reasoning or source spans.
- Do not rely on exact string equality only.
- Prefer conservative rejection when the generated bank is small and human review is expected.

## Output
Return duplicate decision, similarity evidence, and reject reason when applicable.
