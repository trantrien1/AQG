---
name: conflict-filtering
description: Compare supplementary or retrieved context against the uploaded source and reject, downrank, or flag conflicting claims. Use after optional external retrieval and before generation.
---

# Conflict Filtering

Protect source fidelity when extra context is available.

## Workflow
1. Treat the uploaded PDF or dataset as authoritative.
2. Compare retrieved snippets against source claims, formulas, definitions, and numeric values.
3. Drop irrelevant snippets.
4. Downrank weakly related snippets.
5. Flag direct conflicts for human review instead of silently merging them.

## Guardrails
- Do not mix conflicting formulas into one generated question.
- Do not hide conflict notes from downstream grounding.
- Prefer no supplementary context over unsafe supplementary context.

## Output
Return filtered snippets and conflict annotations.
