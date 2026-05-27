---
name: external-retrieval
description: Retrieve supplementary context only when the user or application explicitly permits knowledge expansion beyond the uploaded source. Use before generation for RAG-style enrichment, with the uploaded PDF remaining primary.
---

# External Retrieval

Use external material as supplementary evidence, never as silent replacement for the uploaded source.

## Activation
Use only when external retrieval is explicitly enabled by the user or application configuration.

## Workflow
1. Form a narrow query from the slot topic, skill, and missing context.
2. Retrieve a small set of credible snippets with source metadata.
3. Drop snippets that are irrelevant, low quality, or redundant.
4. Compare supplementary claims against the uploaded source.
5. Mark conflicts and keep external facts labeled as external.

## Guardrails
- Do not use external facts in final questions unless their source is stored.
- Do not override the uploaded PDF with external content.
- Do not retrieve broad background when the source already supports the slot.

## Output
Return ranked snippets with source metadata, relevance notes, and conflict flags.
