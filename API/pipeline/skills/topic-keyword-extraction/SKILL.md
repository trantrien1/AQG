---
name: topic-keyword-extraction
description: Infer planner-ready topics, skills, question patterns, and likely misconceptions from source chunks. Use in PlannerAgent before creating blueprint slots and in slot inference for LLM-driven pattern selection.
---

# Topic Keyword Extraction

Turn chunk text into a compact generation plan.

## Workflow
1. Read the chunk topic, summary, key extracts, and context.
2. Infer one concrete skill the question should test.
3. Choose a meta-pattern such as `computation`, `conceptual`, `reasoning`, or `application`.
4. Write a specific `pattern_id` in snake_case.
5. List likely misconceptions with stable ids, wrong forms, and rationales.
6. Prefer misconceptions visible in the source notation, examples, or common learner errors for that topic.

## Guardrails
- Do not overfit to incidental words in a long mixed chunk.
- Do not invent a niche topic when the chunk only supports a generic concept question.
- Keep misconception descriptions short enough to fit downstream prompts.

## Output
Return:

```json
{
  "meta_pattern": "...",
  "pattern_id": "...",
  "skill": "...",
  "misconceptions": [
    {"id": "...", "wrong_form": "...", "rationale": "..."}
  ]
}
```
