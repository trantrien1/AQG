---
name: curriculum-alignment
description: Check whether a generated question matches the blueprint topic, skill, knowledge component, difficulty target, and requested Bloom level. Use in CriticAgent and RefinerAgent during quality gating.
---

# Curriculum Alignment

Ensure the item tests what the blueprint intended.

## Workflow
1. Compare the stem and answer against the slot topic and inferred skill.
2. Check that the question pattern matches the intended concept or operation.
3. Compare estimated difficulty with target difficulty.
4. Check Bloom level using the actual cognitive operation.
5. Flag drift to a different topic, prerequisite-only task, or unsupported advanced task.

## Guardrails
- Do not accept a mathematically correct item if it tests a different skill.
- Do not force high difficulty when the source chunk supports only recall or comprehension.
- Keep alignment feedback specific enough for refinement.

## Output
Return alignment scores, drift notes, and refine or reject recommendations.
