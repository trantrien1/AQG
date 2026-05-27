---
name: rubric-critique
description: Score generated MCQs across clarity, cognitive depth, Bloom alignment, distractor plausibility, and answer uniqueness with rationale-first judgments. Use in CriticAgent after validation and grounding.
---

# Rubric Critique

Judge item quality in separate traits so one weakness does not hide another.

## Traits
- `clarity`: stem is unambiguous, concise, and asks one target.
- `cognitive_depth`: task depth matches target difficulty.
- `bloom_alignment`: actual cognitive operation matches the requested Bloom level.
- `distractor_plausibility`: wrong options are plausible, parallel, and diagnostic.
- `answer_uniqueness`: exactly one option is correct with no boundary-case ambiguity.

## Workflow
1. Write a short rationale before each score.
2. Score each trait from 0 to 1.
3. Compute aggregate quality from trait scores.
4. Reject or mark for refinement based on the weakest trait, not only the mean.
5. Treat low answer uniqueness as more severe than low style or clarity.

## Guardrails
- Do not reward verbose explanations if the stem is weak.
- Do not let plausible distractors compensate for a non-unique answer.
- Do not judge Bloom level from wording alone; inspect the required operation.

## Output
Return trait rationales, trait scores, aggregate quality, Bloom score, and refinable flag.
