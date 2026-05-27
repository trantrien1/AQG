---
name: source-grounding
description: Check whether generated stems, answers, explanations, distractors, and source quotes are supported by the provided PDF context. Use in CriticAgent after deterministic validation and before final quality acceptance.
---

# Source Grounding

Treat the uploaded source as the authority for generated educational content.

## Workflow
1. Check that the source quote appears in context or has high token overlap with a nearby span.
2. Judge whether stem, answer, and explanation facts are supported by the context.
3. Separate exact quote grounding from inference grounding; a math consequence may be supported by formulas without appearing verbatim.
4. Annotate unsupported numbers, local contradictions, and quote-in-context status.
5. Soft-check that distractors reuse source notation, variables, quantities, formulas, named concepts, or terminology when possible.

## Guardrails
- Do not allow external knowledge to override the source.
- Penalize invented constants, facts, theorems, or examples that are not grounded in the provided context.
- Do not reject a valid symbolic inference solely because the final computed value is absent from the source.
- Keep grounding decisions inspectable for human review.

## Output
Return grounding score and annotations such as `quote_in_context`, unsupported facts, contradiction flags, and distractor trace details.
