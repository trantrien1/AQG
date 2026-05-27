---
name: output-formatting
description: Convert accepted candidates and rejected slots into the final MCQ bank JSON schema expected by the application. Use in FormatterAgent at the end of generation after validation, critique, and selection.
---

# Output Formatting

Create stable records for review, export, and downstream LMS conversion.

## Workflow
1. Clean stem, answer, distractors, explanations, and source quote for display.
2. Shuffle answer options deterministically by `slot_id`.
3. Assign answer key after shuffling.
4. Add source, verification, judging, review, difficulty, tags, attempts, and visual fields.
5. Preserve rejected slot records with topic, attempts, and reject logs.
6. Run final option text issue checks on the formatted record.

## Guardrails
- Do not change mathematical meaning while cleaning display text.
- Preserve inline LaTeX `\(...\)` in stems, options, answers, and explanations; normalize obvious display leaks such as `sqrt(x)`, `binomial(n,k)`, and `x**2` toward LaTeX instead of plain text.
- Do not drop verifier or judge annotations.
- Do not output malformed options, duplicate keys, missing answer key, or detached explanations.
- Keep records JSON-serializable.

## Output
Return an accepted question record or a rejected slot record.
