---
name: visual-rendering
description: Render optional visual specs such as truth tables, matrices, graphs, trees, Venn diagrams, and function graphs into markdown or image assets. Use in RendererAgent after final question records are formatted.
---

# Visual Rendering

Render visuals as helpful assets without blocking question generation.

## Workflow
1. Validate visual type and required fields.
2. Render markdown for simple deterministic types such as truth tables and matrices.
3. Render graph, tree, Venn, or function visuals to image assets when supported dependencies are available.
4. Attach rendered asset paths or markdown back to the question record.
5. Record render errors without failing the whole pipeline.

## Guardrails
- Do not render visuals from invalid or incomplete specs.
- Do not change the question answer to match a rendering failure.
- Always include enough alt text or markdown fallback for review.

## Output
Return rendered count, skipped count, asset paths, and rendering error annotations.
