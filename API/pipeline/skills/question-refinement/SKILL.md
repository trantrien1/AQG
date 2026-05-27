---
name: question-refinement
description: Repair promising MCQ candidates using concrete critique feedback without regenerating from scratch. Use in RefinerAgent when quality or Bloom alignment is below threshold but answer uniqueness remains salvageable.
---

# Question Refinement

Make the smallest safe edit that fixes the critique.

## Workflow
1. Read trait-level critique and identify the blocking weakness.
2. Preserve the source-grounded idea, correct answer, source quote, and verifier hint unless the orchestrator explicitly permits a change.
3. Fix only the criticized part: stem clarity, Bloom operation, distractor plausibility, explanation, or formatting.
4. Keep the item single-answer and source-grounded.
5. Return a full candidate object so validation and critique can rerun.

## Guardrails
- Do not silently change the mathematical answer while keeping the old verifier hint.
- Do not invent a new source quote.
- Do not broaden the stem to hide ambiguity.
- Do not refine candidates with likely multi-answer failure unless the fix explicitly removes the ambiguity.
- Preserve or convert displayed formulas to inline LaTeX `\(...\)`; verifier payloads may remain machine-readable SymPy/JSON.

## Output
Return the refined candidate or the original candidate with an error annotation.
