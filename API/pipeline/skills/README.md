# Direct PDF Skills

This folder contains only the prompt skill snippets used by Direct_PDF_Mode.

Active agents and skills:

- `PdfWriterAgent`: `question-writing`, `bloom-taxonomy-alignment`, `verifier-hint-authoring`, `source-grounding`
- `PdfDistractorAgent`: `distractor-generation`
- `VerifierAgent`: `answer-validation`
- `PdfCriticAgent`: `source-grounding`, `rubric-critique`, `curriculum-alignment`
- `FormatterAgent`: `output-formatting`

The old ingestion, chunking, planner, refiner, and renderer skills were removed
with the legacy chunk pipeline.
