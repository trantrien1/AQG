# Pipeline Skills

Skills follow Anthropic's public skill shape: each skill lives in its own
directory with a required `SKILL.md` containing YAML frontmatter (`name`,
`description`) and concise operating instructions. Deterministic helpers live in
Python modules only when the behavior needs to be executed programmatically.

The active root skill set currently contains 22 skills. Skills under `_future/`
document planned capabilities and are intentionally not loaded by the registry
or exposed in agent manifests until an agent owns them.

## Recent Updates

- Rewrote all active `SKILL.md` files in a concise Anthropic-style format:
  `Workflow`, `Guardrails`, and `Output` sections where useful.
- Moved `external-retrieval` and `conflict-filtering` into `_future/` because no
  active agent owns or executes them yet.
- Moved `duplicate-detection` ownership from `VerifierAgent` to
  `OrchestratorAgent`, matching the current dedup implementation in
  `OrchestratorAgent._is_duplicate_question`.
- Injected skill bodies into the runtime prompt path for all active LLM agents:
  `PlannerAgent`, `QuestionWriterAgent`, `DistractorAgent`, `CriticAgent`, and
  `RefinerAgent`.
- Kept prompt templates for input fields, parse anchors, and output schemas.
  Research rules and operating procedures now live primarily in skills.
- Expanded `distractor-generation` with paper-derived rules: separate
  incorrectness and plausibility, use one misconception per distractor, preserve
  source trace, avoid answer leakage, and reject truncated option fragments.
- Expanded `bloom-taxonomy-alignment` with UTF-8 Vietnamese labels:
  `Nhận biết`, `Thông hiểu`, `Vận dụng`, and `Vận dụng cao`.
- Expanded `verifier-hint-authoring` with concrete verifier payload examples
  that replaced hardcoded writer guidance.
- Updated `pdf-parsing` to reflect actual ingestion behavior, including
  Vietnamese character repair, page-threshold chunking, force-chunk handling,
  and low-quality filtering.

## Agent Ownership

- `OrchestratorAgent`: `pipeline-orchestration`, `duplicate-detection`
- `IngestionAgent`: `pdf-parsing`, `document-classification`,
  `long-document-detection`, `noise-removal`, `chunking`,
  `knowledge-extraction`, `relevance-filtering`
- `PlannerAgent`: `topic-keyword-extraction`, `blueprint-planning`,
  `bloom-taxonomy-alignment`
- `QuestionWriterAgent`: `question-writing`, `bloom-taxonomy-alignment`,
  `verifier-hint-authoring`
- `DistractorAgent`: `distractor-generation`
- `VerifierAgent`: `answer-validation`
- `CriticAgent`: `source-grounding`, `rubric-critique`,
  `curriculum-alignment`
- `RefinerAgent`: `question-refinement`
- `FormatterAgent`: `output-formatting`
- `RendererAgent`: `visual-rendering`

## Runtime Use

`pipeline/skills/registry.py` reads all active root-level `SKILL.md`
frontmatter and lets `run.py` emit both `agent_skills` and
`agent_skill_manifest` in output metadata. Startup fails if an agent references
a missing active skill folder.

Agents can also load the body of their `SKILL.md` files through
`BaseAgent.skill_instructions()`. LLM-backed agents now use those bodies as
runtime operating instructions:

- `PlannerAgent` passes its skill instructions into `slot_inference`.
- `QuestionWriterAgent` injects `question-writing`,
  `bloom-taxonomy-alignment`, and `verifier-hint-authoring` into
  `QuestionWriter`.
- `DistractorAgent` injects `distractor-generation` into `DistractorWriter`.
- `CriticAgent` passes `source-grounding`, `rubric-critique`, and
  `curriculum-alignment` into grounding and multi-trait judge calls.
- `RefinerAgent` injects `question-refinement` into `Refiner`.

Non-LLM agents (`IngestionAgent`, `VerifierAgent`, `FormatterAgent`, and
`RendererAgent`) use skills as executable/spec documentation for deterministic
Python code paths.
