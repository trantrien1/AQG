# AIED-MCQ API - Audit & Handoff Log

Handoff notes for future sessions. This file reflects the cleanup completed after
the direct PDF upload tests.

Last updated: 2026-07-07

---

## 1. Current State

The project now keeps **Direct_PDF_Mode as the only supported generation flow**.
The old PDF-to-text/chunk/planner pipeline has been removed from the active CLI,
backend, frontend, and most source modules.

Direct_PDF_Mode sends the uploaded PDF/pages directly to a vision/file-capable
model, then reuses selected older validation/formatting modules to produce the
same question-bank JSON shape used by the UI.

### Active Data Flow

```text
PDF upload
  -> PdfIngestionComponent.validate
  -> DirectPdfQuestionGenerator
     -> DirectPdfOrchestrator
        -> PdfWriterAgent
        -> PdfDistractorAgent
        -> VerifierAgent
        -> PdfCriticAgent
        -> FormatterAgent
  -> result.json
  -> UI questions / export / review / practice
```

### Active Entry Points

- CLI: `run.py`
- Backend: `web/app.py`
- Background worker: `web/jobs.py`
- Filesystem store: `web/store.py`
- Frontend: `web/frontend/src/app/(dashboard)/upload/page.tsx`
- Generation status page: `web/frontend/src/app/(dashboard)/job/[id]/generate/page.tsx`

---

## 2. What Was Removed

### Removed User-Facing Flow

- Removed upload-to-chunks flow.
- Removed chunk review page: `/job/[id]/chunks`.
- Removed configure-before-generate page: `/job/[id]/configure`.
- Removed plan review endpoints and frontend client helpers.
- Upload now always starts direct PDF generation and navigates to `/job/{id}/generate`.

### Removed Backend/API Pieces

- Removed `/job/{job_id}/chunks` and chunk delete/context endpoints.
- Removed `/job/{job_id}/plan/*` endpoints.
- Removed legacy `run_generation` and `run_ingestion` worker code.
- `web/store.py` no longer reads/writes `chunks.json`, `clean_contexts.json`, or `plan.json`.

### Removed Old Pipeline Modules

Removed modules tied to the legacy chunk/planner/orchestrator path:

- `pipeline/pdf_parser.py`
- `pipeline/chunk_context_builder.py`
- `pipeline/document_preprocessor.py`
- `pipeline/context_retrieval.py`
- `pipeline/fast_plan.py`
- `pipeline/grounding.py`
- `pipeline/visual_renderer.py`
- `pipeline/agent_ablation.py`
- `pipeline/agents/ingestion_agent.py`
- `pipeline/agents/planner_agent.py`
- `pipeline/agents/orchestrator.py`
- `pipeline/agents/question_generator_agent.py`
- `pipeline/agents/critic_agent.py`
- `pipeline/agents/refiner_agent.py`
- `pipeline/agents/renderer_agent.py`

Removed old docling/chunk scripts and tests:

- `scripts/docling_pdf_to_dataset.py`
- `scripts/docling_batch_pdf_to_dataset.py`
- `tests/test_chunk_context_builder.py`
- `tests/test_orchestrator_parallel.py`
- `tests/test_smoke.py`

Removed inactive ingestion/planner/refiner/render skills under `pipeline/skills/`,
including chunking, pdf-parsing, document-classification, blueprint-planning,
question-refinement, visual-rendering, and related future retrieval skills.

---

## 3. What Was Kept Because Direct PDF Reuses It

Do not delete these just because they originally belonged to the older pipeline.
Direct_PDF_Mode still imports or depends on them:

- `pipeline/generator.py`: JSON parsing helpers and schema prompt snippets.
- `pipeline/schema.py`: final question record conversion.
- `pipeline/verifier.py`: deterministic math verification.
- `pipeline/filter.py`: option/distractor sanity validators used by `VerifierAgent`.
- `pipeline/context_utils.py`: prompt context trimming used by retained writer/distractor helpers.
- `pipeline/rule_validator.py`: final deterministic record gate.
- `pipeline/reject.py`: reject summary support for UI/status.
- `pipeline/agents/base.py`: shared skill-loading base class.
- `pipeline/agents/writer_agent.py`: parser/validator helpers reused by `PdfWriterAgent`.
- `pipeline/agents/distractor_agent.py`: distractor parser reused by `PdfDistractorAgent`.
- `pipeline/agents/verifier_agent.py`: reused in DirectPdfOrchestrator.
- `pipeline/agents/formatter_agent.py`: reused in DirectPdfOrchestrator.
- `pipeline/agents/messages.py`: trimmed to direct-mode message classes.

`pipeline/agents/__init__.py` was trimmed so importing `pipeline.agents` no longer
pulls the deleted chunk/planner orchestrator modules.

---

## 4. Current CLI Usage

```powershell
venv\Scripts\python.exe run.py --pdf <file.pdf> -n 10 -o output\questions_direct_pdf.json
```

Optional Bloom lock:

```powershell
venv\Scripts\python.exe run.py --pdf <file.pdf> -n 10 --bloom-level "Vận dụng" -o output\questions_direct_pdf.json
```

Notes:

- `--direct-pdf` is still accepted only for backward compatibility.
- Removed options such as `--chunks-only`, `--force-chunk`, `--save-chunks`, and
  `--target-chars` from the active CLI.
- Direct PDF requires a provider/model path that supports PDF or page-image input.

---

## 5. Current Web Usage

Backend:

```powershell
venv\Scripts\python.exe -m uvicorn web.app:app --host 127.0.0.1 --port 8080 --reload
```

Frontend:

```powershell
cd web\frontend
npm run dev
```

Flow:

1. Open `/upload`.
2. Select a PDF and question count.
3. Upload starts Direct_PDF_Mode immediately.
4. `/job/{id}/generate` polls status.
5. `/job/{id}/questions` shows accepted questions.

---

## 6. Artifact Cleanup

Removed generated/test artifacts:

- `data/`
- `output/`
- `runs/`
- `logs/`
- Python and pytest caches.
- Temporary JSON/log/probe files in `pdftest/`.
- Temporary root scripts such as `poll_job.py`, `web_e2e_test.py`, and
  `web_e2e_jobid.txt`.

Kept PDF samples in `pdftest/` because they are useful for future direct PDF
manual tests.

`.gitignore` was updated to keep these artifacts out of future status noise:

- `.pytest_cache/`
- `data/`
- `runs/`
- `logs/`
- `output/`
- `pdftest/*.json`
- `pdftest/*.log`
- `pdftest/_*.py`

---

## 7. Verification Performed

After cleanup, these checks were run successfully:

```powershell
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe -m compileall -q pipeline web run.py
cd web\frontend; npm run lint
```

Results:

- Python tests: `21 passed`
- Python compile check: passed
- Frontend ESLint: passed

New direct-only smoke test added:

- `tests/test_direct_pdf_smoke.py`

It verifies:

- Direct PDF modules import without the removed chunk pipeline.
- Direct PDF JSON parsing accepts a valid MCQ payload.
- PDF validation reports missing files cleanly.

---

## 8. Remaining Notes / Gotchas

- Direct_PDF_Mode still depends on selected older helper files listed in section 3.
  Delete those only after checking imports from `pipeline/direct_pdf/**` and tests.
- `filter.py` was trimmed to deterministic option/distractor validation. The old
  NLI/grounding slot filter was removed because it depended on the deleted
  `pipeline/grounding.py` path.
- `pipeline/skills/registry.py` now lists only direct-mode skill snippets.
- Existing PDF samples under `pdftest/` are intentionally retained.
- The repository had pre-existing staged changes before this cleanup. Be careful
  before committing: staged deletions for files like `pipeline/agents/writer_agent.py`
  or `pipeline/agents/distractor_agent.py` would break Direct_PDF_Mode if committed
  as deletions.

---

## 9. Recommended Next Steps

- Run one manual web upload with a small PDF and confirm `/upload -> /generate -> /questions`.
- Consider adding a lightweight backend integration test for `/upload` using a tiny
  generated PDF and monkeypatched `run_direct_generation`.
- Review old docs such as `README_pipeline.md` if they are still needed; they likely
  describe removed chunk/planner behavior.
- Normalize or clean git index before committing, because the worktree had staged
  changes from before this cleanup.
