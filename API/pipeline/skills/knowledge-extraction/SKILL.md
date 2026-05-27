---
name: knowledge-extraction
description: Extract compact summaries and key educational passages from cleaned math document chunks. Use in IngestionAgent after chunking to prepare definitions, formulas, examples, exercises, and answer-bearing text for planning and MCQ generation.
---

# Knowledge Extraction

Surface the educational content most useful for grounded MCQs.

## Workflow
1. Create a short source-faithful summary of the chunk.
2. Extract key passages containing definitions, formulas, theorems, worked examples, exercises, diagrams captions, or solutions.
3. Keep each extract close to the original wording so source quotes can still match.
4. Prefer content that can support a clear correct answer and plausible misconceptions.
5. Store extracted content on the same unit; do not create detached facts.

## Guardrails
- Do not add facts absent from the source.
- Do not convert examples into generalized rules unless the source states the rule.
- Keep symbolic notation intact.

## Output
Return:

```json
{"summary": "...", "key_extracts": ["..."]}
```
