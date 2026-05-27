---
name: document-classification
description: Classify uploaded learning documents before MCQ generation. Use in IngestionAgent when a PDF or text dataset enters the pipeline so preprocessing can adapt to textbooks, exercises, slides, papers, or mixed math documents.
---

# Document Classification

Assign a coarse document type that helps later preprocessing without overclaiming the subject or curriculum.

## Workflow
1. Inspect source filename, metadata, headings, and early meaningful text.
2. Choose one broad type: `exercise_or_textbook`, `slide`, `paper`, `exam_or_question_bank`, or `general_math_document`.
3. Record whether the document appears structured, mixed, OCR-noisy, or mostly exercises.
4. Leave detailed topic and skill selection to planning and extraction skills.

## Guardrails
- Do not infer a subject from weak evidence.
- Do not let document type override the source text.
- Prefer `general_math_document` when signals conflict.

## Output
Return a compact report:

```json
{"document_type": "...", "source": "...", "structure_notes": "..."}
```
