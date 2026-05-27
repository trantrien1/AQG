---
name: pipeline-orchestration
description: Coordinate the end-to-end MCQ bank generation job across ingestion, planning, writing, distractor generation, verification, critique, refinement, formatting, and rendering. Use inside OrchestratorAgent for full pipeline runs and per-slot candidate selection.
---

# Pipeline Orchestration

Run agents in the fixed order expected by the application. Preserve every decision needed for debugging, human review, and cost analysis.

## Workflow
1. Ingest the source or accept a prebuilt dataset.
2. Build blueprint slots with source chunk, topic, Bloom level, target difficulty, pattern, skill, and misconceptions.
3. For each slot, generate multiple stem-answer candidates before distractors.
4. Add distractors only after a candidate has a clear correct answer and explanation.
5. Verify machine-checkable answers before spending critique calls.
6. Critique grounding, rubric quality, Bloom alignment, distractor plausibility, and answer uniqueness.
7. Refine only salvageable candidates; reject verifier failures and likely multi-answer items.
8. Deduplicate against accepted questions before final selection.
9. Format accepted and rejected records with source, verification, judging, review, attempts, and cost metadata.
10. Render optional visuals without blocking the whole run.

## Selection Rules
- Prefer `verified=true` candidates over unverifiable candidates when quality is comparable.
- Treat verifier parse errors as rejection-worthy; treat `engine=none` as unverifiable, not failed.
- Keep reject logs concise but specific enough to drive repair attempts.
- Stop cleanly on budget exceptions and return partial progress metadata.

## Output
Return accepted questions, rejected slots, blueprint summary, cost report, stopped reason, agent skill map, and skill manifest.
