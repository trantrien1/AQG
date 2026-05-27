---
name: blueprint-planning
description: Build MCQ blueprint slots across dataset units, Bloom levels, difficulty targets, inferred skills, question patterns, and misconceptions. Use in PlannerAgent before QuestionWriterAgent runs.
---

# Blueprint Planning

Decide what questions to generate and from which source chunks.

## Workflow
1. Select source units in a balanced way across available chunks.
2. Assign Bloom levels from the requested distribution or explicit user level.
3. Assign target difficulty values consistent with the Bloom level.
4. Attach topic, skill, pattern id, expected question type, and inferred misconceptions.
5. Create deterministic `slot_id` values.
6. Preserve `doc_id` so every slot can retrieve its source context.

## Guardrails
- Avoid overusing one chunk unless the dataset is tiny.
- Do not ask for a high-Bloom item from a chunk that only contains a definition unless the context supports reasoning or application.
- Keep fallback patterns broad when inference fails.

## Output
Return slots with:

```json
{
  "slot_id": "q_001",
  "doc_id": "...",
  "topic": "...",
  "cognitive_level": "...",
  "difficulty_target": 0.5,
  "question_pattern": "...",
  "skill": "..."
}
```
