---
name: answer-validation
description: Validate the correct answer, verifier payload, distractor uniqueness, multi-answer risk, and post-clean option sanity. Use in VerifierAgent before critique and final formatting.
---

# Answer Validation

Run deterministic checks before spending judge calls.

## Workflow
1. Normalize the verifier hint schema and fill simple missing expected values when safe.
2. Run the symbolic, numeric, graph, matrix, probability, modular, geometry, recurrence, or logic verifier when available.
3. Reject `verified=false`.
4. Reject verifier parse errors when an engine attempted to run; do not confuse this with `engine=none`.
5. When the correct answer verifies, run the same verifier against every distractor to catch multi-answer items.
6. Validate post-clean option text, not only raw LLM text.
7. Check duplicate distractors, category diversity, display syntax, visual consistency, and item-writing flaws.

## Guardrails
- Do not let an LLM judge override a deterministic verifier failure.
- Do not accept fragments, dangling connectors, empty options, or overlong derivations as option text.
- Do not accept repeated misconception categories when categories are present.
- Preserve verification annotations for downstream formatting and review.

## Output
Return verification annotations or a concrete reject reason.
