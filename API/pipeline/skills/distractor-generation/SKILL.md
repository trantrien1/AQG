---
name: distractor-generation
description: Generate plausible wrong MCQ options grounded in explicit misconceptions, source context, and the correct answer shape. Use in DistractorAgent after QuestionWriterAgent has produced the stem, correct answer, explanation, source quote, and verifier hint.
---

# Distractor Generation

Generate wrong options that are educationally diagnostic, not random wrong answers.

## Research-Informed Procedure
1. Treat `incorrectness` and `plausibility` as separate goals. A distractor must be wrong and still look like a natural learner mistake.
2. Use one explicit misconception or strategy per distractor.
3. Keep answer type and grammar parallel to the correct answer: number with number, formula with formula, statement with statement.
4. Reuse source notation, variables, quantities, named concepts, or terminology so each distractor has a light trace in the material.
5. Avoid answer leakage. Do not copy final values, answer-specific phrases, or synonymous wording from the correct answer unless all options share the same scaffold.
6. Generate concise, complete, display-ready option text, not a derivation.
7. Select diverse final distractors; avoid three phrasings of the same mistake.

## Guards
- Reject `all of the above`, `none of the above`, and equivalent Vietnamese forms.
- Avoid absolute clue words such as `always`, `never`, `luôn luôn`, and `không bao giờ` unless the stem explicitly tests such wording.
- Avoid options that are much longer, much more technical, or much vaguer than the correct answer.
- Avoid copying a full source sentence as a distractor unless the item asks students to choose among source statements.
- Never output a truncated fragment such as `ra 0.`.
- Use inline LaTeX `\(...\)` for displayed formulas/expressions in distractor text and distractor explanations.

## Output
Return exactly three entries with:

```json
{
  "distractor_text": "...",
  "distractor_category_text": "misconception_id",
  "distractor_explanation_text": "why this option is wrong"
}
```
