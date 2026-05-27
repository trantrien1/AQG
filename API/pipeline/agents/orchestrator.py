"""OrchestratorAgent — điều phối 8 agents thành pipeline refactor.

Pipeline đầy đủ (run_full_pipeline):
    PDF
     │
     ▼
    [IngestionAgent]    pdf_parser → dataset (chunks)
     │
     ▼
    [PlannerAgent]      LLM-driven slot inference (concept + pattern + skill +
                        misconceptions theo Savaal + MCQG-SRefine)
     │
     ▼ với mỗi slot:
    [QuestionWriterAgent]  Stage 1: stem + answer + reasoning + verifier hint
                            (KHÔNG distractor — tách concern theo CoE 3-stage)
     │
     ▼ với mỗi candidate từ Writer:
    [DistractorAgent]   Stage 2: 3 distractor gắn misconception cụ thể
     │
     ▼
    [VerifierAgent]     Symbolic verify + natural→SymPy translation
                        + multi-answer check + distractor validator + IWF
     │
     ▼ candidate sống sót, song song:
    [CriticAgent]       Multi-trait rubric: clarity / cognitive_depth /
                        distractor_plausibility / answer_uniqueness
                        (rationale-before-score, RMTS-style)
     │
     ▼ nếu quality dưới ngưỡng nhưng refinable=True:
    [RefinerAgent]      Iterative critique→correction (MCQG-SRefine, max 1 lần)
                        sau đó re-verify + re-critic
     │
     ▼ pick best candidate cho slot
    [FormatterAgent]    candidate → final record (shuffle options, KC, difficulty)
     │
     ▼
    [RendererAgent]     visual spec → PNG/markdown
     │
     ▼
    output
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import BaseAgent
from .messages import (
    CriticRequest, CriticResponse,
    DistractorRequest, DistractorResponse,
    FormatAcceptedRequest, FormatRejectedRequest,
    GenerateRequest, GenerateResponse,
    IngestionRequest, IngestionResponse,
    PlanRequest, PlanResponse,
    RefineRequest, RefineResponse,
    RenderRequest, RenderResponse,
    SlotResult,
    VerifyRequest, VerifyResponse,
    WriteRequest, WriteResponse,
)
from .ingestion_agent import IngestionAgent
from .planner_agent import PlannerAgent
from .question_generator_agent import QuestionGeneratorAgent
from .writer_agent import QuestionWriterAgent
from .distractor_agent import DistractorAgent
from .verifier_agent import VerifierAgent
from .critic_agent import CriticAgent
from .refiner_agent import RefinerAgent
from .formatter_agent import FormatterAgent
from .renderer_agent import RendererAgent
from .. import config as cfg
from .. import grounding as gj
from .. import reject as reject_mod
from ..blueprint import summary as bp_summary
from ..fast_plan import build_fast_plan
from ..context_retrieval import expand_context, find_alternative_chunk
from ..customization import GenerationConfig
from ..filter import filter_by_nli
from ..generator import BatchQuestionGenerator
from ..llm_client import BudgetExceeded, get_tracker
from ..schema import record_option_text_issues
from ..skills.registry import agent_skill_manifest, validate_skill_references


class CancelledError(Exception):
    """Raised when the cancel-flag callback returns True."""


ProgressCallback = Callable[[float, str, int, int], None]
CancelCheck = Callable[[], bool]

def _within_total_attempt_limit(slot_cursor: int, max_total_attempts: int) -> bool:
    return max_total_attempts <= 0 or slot_cursor < max_total_attempts

def _attempts_progress_text(slot_cursor: int, max_total_attempts: int) -> str:
    if max_total_attempts <= 0:
        return f'attempts={slot_cursor}'
    return f'attempts={slot_cursor}/{max_total_attempts}'


class OrchestratorAgent(BaseAgent):
    """Điều phối 8 sub-agents.

    Public methods:
        ingest(pdf_path)                — IngestionAgent only (web /upload)
        run(dataset, num_questions, …)  — Plan + WRITE → DISTRACT → Verify → Critic → Refine → Format
        run_full_pipeline(pdf_path, …)  — Ingest + run
    """

    def __init__(self, repair_attempts: int = cfg.NUM_REPAIR_ATTEMPTS):
        super().__init__('orchestrator', skills=[
            'pipeline-orchestration',
            'duplicate-detection',
        ])
        self.repair_attempts = repair_attempts

        # 8 sub-agents (stateless — share giữa các slot, thread-safe via copy)
        self.ingestion = IngestionAgent()
        self.planner = PlannerAgent()
        self.generator = QuestionGeneratorAgent()
        self.batch_generator = BatchQuestionGenerator()
        self.writer = QuestionWriterAgent()
        self.distractor = DistractorAgent()
        self.verifier = VerifierAgent()
        self.critic = CriticAgent()
        self.refiner = RefinerAgent()
        self.formatter = FormatterAgent()
        self.renderer = RendererAgent()

    def skill_map(self) -> Dict[str, List[str]]:
        return {
            'OrchestratorAgent': self.skills,
            'IngestionAgent': self.ingestion.skills,
            'PlannerAgent': self.planner.skills,
            'QuestionGeneratorAgent': self.generator.skills,
            'QuestionWriterAgent': self.writer.skills,
            'DistractorAgent': self.distractor.skills,
            'VerifierAgent': self.verifier.skills,
            'CriticAgent': self.critic.skills,
            'RefinerAgent': self.refiner.skills,
            'FormatterAgent': self.formatter.skills,
            'RendererAgent': self.renderer.skills,
        }

    def skill_manifest(self) -> Dict[str, List[Dict[str, str]]]:
        return agent_skill_manifest(self.skill_map())

    def missing_skill_references(self) -> Dict[str, List[str]]:
        missing: Dict[str, List[str]] = {}
        for agent, skills in self.skill_map().items():
            miss = validate_skill_references(skills)
            if miss:
                missing[agent] = miss
        return missing

    # ==================================================================
    # Public API
    # ==================================================================

    def ingest(self, pdf_path: str, target_chars: int = 1000,
               chunk_page_threshold: int = 100,
               force_chunk: bool = False) -> IngestionResponse:
        return self.ingestion.run(IngestionRequest(
            pdf_path=pdf_path, target_chars=target_chars,
            chunk_page_threshold=chunk_page_threshold, force_chunk=force_chunk,
        ))

    @staticmethod
    def _target_bloom(distribution: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """Nếu user chọn 1 Bloom level (fraction=1.0) thì trả về tên level đó.
        Còn nếu mixed/None thì trả None — Critic không gắt về Bloom alignment."""
        if not distribution:
            return None
        single = [d for d in distribution if d.get('fraction', 0) >= 0.99]
        if len(single) == 1:
            return single[0].get('cognitive_level')
        return None

    def run(
        self,
        dataset: Dict[str, Any],
        num_questions: int,
        num_samples: int = cfg.NUM_SAMPLES_PER_SLOT,
        use_nli: bool = False,
        seed: int = 42,
        out_dir: Optional[str] = None,
        progress_cb: Optional[ProgressCallback] = None,
        difficulty_distribution: Optional[List[Dict[str, Any]]] = None,
        plan_resp: Optional[PlanResponse] = None,
        cancel_check: Optional[CancelCheck] = None,
        generation_config: Optional[GenerationConfig] = None,
        mode: str = cfg.DEFAULT_GENERATION_MODE,
    ) -> Dict[str, Any]:
        mode = (mode or cfg.DEFAULT_GENERATION_MODE or 'fast').lower()
        # ---- Step 1: Plan ----
        if plan_resp is None:
            if progress_cb:
                progress_cb(0.0, 'building fast internal plan...' if mode == 'fast' else 'planning slots...', 0, 0)
            if mode == 'fast':
                plan_slots = max(
                    num_questions,
                    int(round(num_questions * max(1.0, cfg.FAST_PLAN_SLOT_MULTIPLIER))),
                )
                slots = build_fast_plan(
                    dataset,
                    plan_slots,
                    seed=seed,
                    difficulty_distribution=difficulty_distribution,
                )
                plan_resp = PlanResponse(slots=slots, summary=bp_summary(slots))
            else:
                plan_resp = self.planner.run(PlanRequest(
                    dataset=dataset, num_questions=num_questions, seed=seed,
                    difficulty_distribution=difficulty_distribution,
                ))
        slots = plan_resp.slots
        if progress_cb:
            progress_cb(0.02, f'blueprint: {len(slots)} slots', 0, 0)

        # ---- Step 2: Per-slot Write → Distract → Verify → Critic → (Refine) ----
        return self._run_until_target_accepted(
            slots=slots,
            dataset=dataset,
            target_accepted=num_questions,
            num_samples=num_samples,
            use_nli=use_nli,
            out_dir=out_dir,
            progress_cb=progress_cb,
            plan_summary=plan_resp.summary,
            cancel_check=cancel_check,
            generation_config=generation_config,
            mode=mode,
        )

    def _run_until_target_accepted(
        self,
        slots: List[Dict[str, Any]],
        dataset: Dict[str, Any],
        target_accepted: int,
        num_samples: int,
        use_nli: bool,
        out_dir: Optional[str],
        progress_cb: Optional[ProgressCallback],
        plan_summary: Dict[str, Any],
        cancel_check: Optional[CancelCheck] = None,
        generation_config: Optional[GenerationConfig] = None,
        mode: str = 'fast',
    ) -> Dict[str, Any]:
        """Generate until the requested number of formatted accepted records exists.

        Retry budget:
          * `MAX_SLOT_ATTEMPTS` round-attempts per slot (each round = a fresh
            writer call with optionally widened context).
          * Optional global cap only when `MAX_JOB_ATTEMPT_MULTIPLIER > 0`.
        """
        target = max(0, int(target_accepted))
        questions: List[Dict[str, Any]] = []
        rejected_records: List[Dict[str, Any]] = []
        accepted_refs: List[Dict[str, str]] = []
        stopped_reason: Optional[str] = None
        valid_slots: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        for slot in slots:
            doc = dataset.get(slot.get('doc_id'))
            if not doc:
                fmt_resp = self.formatter.run(FormatRejectedRequest(
                    slot=slot,
                    slot_result=SlotResult(
                        slot_id=slot.get('slot_id', ''),
                        chosen=None,
                        reject_log=[reject_mod.make(
                            'context_missing',
                            stage='orchestrator',
                            attempt=0,
                            slot_id=slot.get('slot_id'),
                            message=f'missing doc_id: {slot.get("doc_id")}',
                            action='skip_slot',
                        )],
                    ),
                ))
                rejected_records.append(fmt_resp.record)
            else:
                valid_slots.append((slot, doc))

        if target > 0 and not valid_slots:
            stopped_reason = 'no valid source slots'

        # Per-slot tracking: how many round-attempts have we burned on this slot?
        slot_attempt_counts: Dict[str, int] = {}
        slot_used_chunks: Dict[str, List[str]] = {}
        max_total_attempts = (
            max(target, target * cfg.MAX_JOB_ATTEMPT_MULTIPLIER)
            if cfg.MAX_JOB_ATTEMPT_MULTIPLIER > 0 else 0
        )
        mode = (mode or 'fast').lower()
        slot_cursor = 0

        # Stamp the generation config onto each base slot once so writer/
        # distractor/critic prompts can read it. Done here (not in caller)
        # so plan slots stay un-mutated on disk.
        if generation_config and not generation_config.is_default():
            from ..customization import apply_to_slot as _apply_cust
            valid_slots = [
                (_apply_cust(slot, generation_config), doc)
                for slot, doc in valid_slots
            ]

        def _was_cancelled() -> bool:
            try:
                return bool(cancel_check and cancel_check())
            except Exception:
                return False

        if mode == 'fast' and cfg.FAST_BATCH_ENABLED:
            return self._run_fast_batch_until_target(
                valid_slots=valid_slots,
                dataset=dataset,
                target=target,
                num_samples=num_samples,
                use_nli=use_nli,
                out_dir=out_dir,
                progress_cb=progress_cb,
                plan_summary=plan_summary,
                cancel_check=cancel_check,
                generation_config=generation_config,
                rejected_records=rejected_records,
                max_total_attempts=max_total_attempts,
                slot_attempt_counts=slot_attempt_counts,
                slot_used_chunks=slot_used_chunks,
            )

        if mode == 'fast' and cfg.FAST_PARALLEL_WORKERS > 1:
            return self._run_fast_parallel_until_target(
                valid_slots=valid_slots,
                dataset=dataset,
                target=target,
                num_samples=num_samples,
                use_nli=use_nli,
                out_dir=out_dir,
                progress_cb=progress_cb,
                plan_summary=plan_summary,
                cancel_check=cancel_check,
                generation_config=generation_config,
                rejected_records=rejected_records,
                max_total_attempts=max_total_attempts,
                slot_attempt_counts=slot_attempt_counts,
                slot_used_chunks=slot_used_chunks,
            )

        while (
            len(questions) < target
            and valid_slots
            and not stopped_reason
            and _within_total_attempt_limit(slot_cursor, max_total_attempts)
        ):
            if _was_cancelled():
                stopped_reason = 'cancelled'
                break

            base_slot, doc = valid_slots[slot_cursor % len(valid_slots)]
            base_slot_id = base_slot.get('slot_id', '')
            attempt_no = slot_attempt_counts.get(base_slot_id, 0) + 1

            # Skip slots that have exhausted their per-slot budget.
            if attempt_no > cfg.MAX_SLOT_ATTEMPTS:
                slot_cursor += 1
                # If every remaining slot is exhausted, stop.
                if all(
                    slot_attempt_counts.get(s.get('slot_id', ''), 0) >= cfg.MAX_SLOT_ATTEMPTS
                    for s, _ in valid_slots
                ):
                    stopped_reason = 'max_attempts_exceeded'
                continue

            slot_attempt_counts[base_slot_id] = attempt_no
            slot = dict(base_slot)
            if attempt_no > 1:
                slot['slot_id'] = f'{base_slot_id}_r{attempt_no:02d}'

            # Pick context — widen on retries, fall back to alternative chunk.
            used_chunks = slot_used_chunks.setdefault(base_slot_id, [])
            context, chunk_ids, ctx_action = expand_context(
                dataset, base_slot, attempt_no,
            )
            if ctx_action in {'context_missing', 'context_too_noisy'} or not context.strip():
                result = SlotResult(
                    slot_id=slot['slot_id'],
                    chosen=None,
                    reject_log=[reject_mod.make(
                        ctx_action if ctx_action in {'context_missing', 'context_too_noisy'} else 'context_missing',
                        stage='context_selection',
                        attempt=attempt_no,
                        slot_id=slot['slot_id'],
                        message=f'clean context unavailable for doc_id={base_slot.get("doc_id", "")}',
                        action='expand_context' if attempt_no < cfg.MAX_SLOT_ATTEMPTS else 'fail_slot',
                        selected_chunk_ids=chunk_ids,
                    )],
                    attempts=attempt_no,
                )
                if attempt_no >= cfg.MAX_SLOT_ATTEMPTS:
                    fmt_resp = self.formatter.run(FormatRejectedRequest(
                        slot=slot, slot_result=result,
                    ))
                    rejected_records.append(fmt_resp.record)
                slot_cursor += 1
                continue
            slot['selected_chunk_ids'] = chunk_ids
            slot['selected_context_ids'] = chunk_ids
            slot['context_selection_action'] = ctx_action
            slot['existing_question_spans'] = self._existing_question_spans_for_context(
                dataset, base_slot, chunk_ids,
            )
            for cid in chunk_ids:
                if cid and cid not in used_chunks:
                    used_chunks.append(cid)

            if progress_cb:
                ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
                progress_cb(
                    min(0.94, ratio),
                    (
                        f'accepted {len(questions)}/{target}; '
                        f'{mode} generator; '
                        f'slot {slot_cursor % len(valid_slots) + 1}/{len(valid_slots)} '
                        f'attempt {attempt_no}/{cfg.MAX_SLOT_ATTEMPTS}: '
                        f'{slot.get("topic", "")[:40]}'
                    ),
                    len(questions),
                    len(rejected_records),
                )

            try:
                result = self._process_slot(
                    slot, context, num_samples,
                    existing_questions=accepted_refs,
                    use_nli=use_nli,
                    cancel_check=cancel_check,
                    generation_config=generation_config,
                    attempt_no=attempt_no,
                    mode=mode,
                )
            except CancelledError:
                stopped_reason = 'cancelled'
                break
            except BudgetExceeded as e:
                stopped_reason = f'budget exceeded: {e}'
                if progress_cb:
                    ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
                    progress_cb(
                        min(0.94, ratio), stopped_reason,
                        len(questions), len(rejected_records),
                    )
                break
            except Exception as e:
                import traceback
                result = SlotResult(
                    slot_id=slot['slot_id'],
                    chosen=None,
                    reject_log=[reject_mod.make(
                        'orchestrator_error',
                        stage='orchestrator',
                        attempt=attempt_no,
                        slot_id=slot['slot_id'],
                        message=f'{e}\n{traceback.format_exc()[:300]}',
                    )],
                )

            if result.chosen:
                fmt_resp = self.formatter.run(FormatAcceptedRequest(
                    slot=slot, candidate=result.chosen, doc=doc,
                    attempts=result.attempts,
                ))
                format_issues = record_option_text_issues(fmt_resp.record)
                if format_issues:
                    rejected = self.formatter.run(FormatRejectedRequest(
                        slot=slot,
                        slot_result=SlotResult(
                            slot_id=slot['slot_id'],
                            chosen=None,
                            reject_log=[reject_mod.make(
                                'format_error',
                                stage='formatter',
                                attempt=attempt_no,
                                slot_id=slot['slot_id'],
                                message=f'final formatted sanity: {format_issues}',
                                action='skip_candidate',
                            )],
                            attempts=result.attempts,
                        ),
                    ))
                    rejected_records.append(rejected.record)
                else:
                    questions.append(fmt_resp.record)
                    accepted_refs.append(self._accepted_question_ref(result.chosen))
            else:
                # Decide whether to retry this slot OR move on.
                will_retry = (
                    attempt_no < cfg.MAX_SLOT_ATTEMPTS
                    and not _was_cancelled()
                    and any(
                        reject_mod.coerce(e).get('reason_code')
                        in (
                            reject_mod.CONTEXT_REPAIRABLE_CODES
                            | reject_mod.REPAIRABLE_DISTRACTOR_CODES
                            | reject_mod.REPAIRABLE_WRITER_CODES
                        )
                        for e in result.reject_log
                    )
                )
                if not will_retry:
                    fmt_resp = self.formatter.run(FormatRejectedRequest(
                        slot=slot, slot_result=result,
                    ))
                    rejected_records.append(fmt_resp.record)

            slot_cursor += 1

        if stopped_reason == 'cancelled' and progress_cb:
            ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
            progress_cb(min(0.95, ratio), 'cancelled by user',
                        len(questions), len(rejected_records))

        if progress_cb:
            progress_cb(0.95, 'finalizing question bank...',
                        len(questions), len(rejected_records))

        render_result = None
        if out_dir and questions:
            if progress_cb:
                progress_cb(0.98, 'rendering visuals...',
                            len(questions), len(rejected_records))
            render_result = self.renderer.run(
                RenderRequest(records=questions, out_dir=out_dir)
            )

        if progress_cb:
            if stopped_reason == 'cancelled':
                status_msg = 'cancelled'
            else:
                status_msg = 'done' if len(questions) >= target else 'done partial'
            progress_cb(1.0, status_msg, len(questions), len(rejected_records))

        return {
            'questions': questions,
            'rejected': rejected_records,
            'blueprint_summary': plan_summary,
            'cost': get_tracker().report(),
            'render_result': render_result,
            'stopped_reason': stopped_reason,
            'reject_summary': reject_mod.summarize(rejected_records),
            'mode': mode,
            'attempts': {
                'total_slot_attempts': slot_cursor,
                'max_total_attempts': max_total_attempts,
                'per_slot': slot_attempt_counts,
            },
        }

    def _run_fast_parallel_until_target(
        self,
        *,
        valid_slots: List[Tuple[Dict[str, Any], Dict[str, Any]]],
        dataset: Dict[str, Any],
        target: int,
        num_samples: int,
        use_nli: bool,
        out_dir: Optional[str],
        progress_cb: Optional[ProgressCallback],
        plan_summary: Dict[str, Any],
        cancel_check: Optional[CancelCheck],
        generation_config: Optional[GenerationConfig],
        rejected_records: List[Dict[str, Any]],
        max_total_attempts: int,
        slot_attempt_counts: Dict[str, int],
        slot_used_chunks: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """Fast Mode slot generation with bounded parallel LLM calls."""
        questions: List[Dict[str, Any]] = []
        accepted_refs: List[Dict[str, str]] = []
        stopped_reason: Optional[str] = None
        slot_cursor = 0
        workers = max(1, int(cfg.FAST_PARALLEL_WORKERS or 1))

        def _was_cancelled() -> bool:
            try:
                return bool(cancel_check and cancel_check())
            except Exception:
                return False

        def _handle_slot_result(
            slot: Dict[str, Any],
            doc: Dict[str, Any],
            attempt_no: int,
            result: SlotResult,
        ) -> None:
            if result.chosen and len(questions) < target:
                if accepted_refs and self._is_duplicate_question(result.chosen, accepted_refs):
                    rejected = self.formatter.run(FormatRejectedRequest(
                        slot=slot,
                        slot_result=SlotResult(
                            slot_id=slot['slot_id'],
                            chosen=None,
                            reject_log=[reject_mod.make(
                                'duplicate',
                                stage='validator',
                                attempt=attempt_no,
                                slot_id=slot['slot_id'],
                                message='duplicate with previously accepted in parallel batch',
                                action='skip_candidate',
                            )],
                            attempts=result.attempts,
                        ),
                    ))
                    rejected_records.append(rejected.record)
                    return

                fmt_resp = self.formatter.run(FormatAcceptedRequest(
                    slot=slot, candidate=result.chosen, doc=doc,
                    attempts=result.attempts,
                ))
                format_issues = record_option_text_issues(fmt_resp.record)
                if format_issues:
                    rejected = self.formatter.run(FormatRejectedRequest(
                        slot=slot,
                        slot_result=SlotResult(
                            slot_id=slot['slot_id'],
                            chosen=None,
                            reject_log=[reject_mod.make(
                                'format_error',
                                stage='formatter',
                                attempt=attempt_no,
                                slot_id=slot['slot_id'],
                                message=f'final formatted sanity: {format_issues}',
                                action='skip_candidate',
                            )],
                            attempts=result.attempts,
                        ),
                    ))
                    rejected_records.append(rejected.record)
                    return

                questions.append(fmt_resp.record)
                accepted_refs.append(self._accepted_question_ref(result.chosen))
                return

            if not result.chosen:
                will_retry = (
                    attempt_no < cfg.MAX_SLOT_ATTEMPTS
                    and not _was_cancelled()
                    and any(
                        reject_mod.coerce(e).get('reason_code')
                        in (
                            reject_mod.CONTEXT_REPAIRABLE_CODES
                            | reject_mod.REPAIRABLE_DISTRACTOR_CODES
                            | reject_mod.REPAIRABLE_WRITER_CODES
                        )
                        for e in result.reject_log
                    )
                )
                if not will_retry:
                    fmt_resp = self.formatter.run(FormatRejectedRequest(
                        slot=slot, slot_result=result,
                    ))
                    rejected_records.append(fmt_resp.record)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='fast-slot') as pool:
            while (
                len(questions) < target
                and valid_slots
                and not stopped_reason
                and _within_total_attempt_limit(slot_cursor, max_total_attempts)
            ):
                if _was_cancelled():
                    stopped_reason = 'cancelled'
                    break

                futures: Dict[Any, Tuple[Dict[str, Any], Dict[str, Any], int]] = {}
                while (
                    len(futures) < workers
                    and len(questions) + len(futures) < target
                    and _within_total_attempt_limit(slot_cursor, max_total_attempts)
                ):
                    base_slot, doc = valid_slots[slot_cursor % len(valid_slots)]
                    base_slot_id = base_slot.get('slot_id', '')
                    attempt_no = slot_attempt_counts.get(base_slot_id, 0) + 1

                    if attempt_no > cfg.MAX_SLOT_ATTEMPTS:
                        slot_cursor += 1
                        if all(
                            slot_attempt_counts.get(s.get('slot_id', ''), 0) >= cfg.MAX_SLOT_ATTEMPTS
                            for s, _ in valid_slots
                        ):
                            stopped_reason = 'max_attempts_exceeded'
                            break
                        continue

                    slot_attempt_counts[base_slot_id] = attempt_no
                    slot = dict(base_slot)
                    if attempt_no > 1:
                        slot['slot_id'] = f'{base_slot_id}_r{attempt_no:02d}'

                    used_chunks = slot_used_chunks.setdefault(base_slot_id, [])
                    context, chunk_ids, ctx_action = expand_context(
                        dataset, base_slot, attempt_no,
                    )
                    if ctx_action in {'context_missing', 'context_too_noisy'} or not context.strip():
                        result = SlotResult(
                            slot_id=slot['slot_id'],
                            chosen=None,
                            reject_log=[reject_mod.make(
                                ctx_action if ctx_action in {'context_missing', 'context_too_noisy'} else 'context_missing',
                                stage='context_selection',
                                attempt=attempt_no,
                                slot_id=slot['slot_id'],
                                message=f'clean context unavailable for doc_id={base_slot.get("doc_id", "")}',
                                action='expand_context' if attempt_no < cfg.MAX_SLOT_ATTEMPTS else 'fail_slot',
                                selected_chunk_ids=chunk_ids,
                            )],
                            attempts=attempt_no,
                        )
                        if attempt_no >= cfg.MAX_SLOT_ATTEMPTS:
                            _handle_slot_result(slot, doc, attempt_no, result)
                        slot_cursor += 1
                        continue

                    slot['selected_chunk_ids'] = chunk_ids
                    slot['selected_context_ids'] = chunk_ids
                    slot['context_selection_action'] = ctx_action
                    slot['existing_question_spans'] = self._existing_question_spans_for_context(
                        dataset, base_slot, chunk_ids,
                    )
                    for cid in chunk_ids:
                        if cid and cid not in used_chunks:
                            used_chunks.append(cid)

                    if progress_cb:
                        ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
                        progress_cb(
                            min(0.94, ratio),
                            (
                                f'accepted {len(questions)}/{target}; fast parallel x{workers}; '
                                f'slot {slot_cursor % len(valid_slots) + 1}/{len(valid_slots)} '
                                f'attempt {attempt_no}/{cfg.MAX_SLOT_ATTEMPTS}: '
                                f'{slot.get("topic", "")[:40]}'
                            ),
                            len(questions),
                            len(rejected_records),
                        )

                    fut = pool.submit(
                        self._process_slot,
                        slot, context, num_samples,
                        existing_questions=accepted_refs,
                        use_nli=use_nli,
                        cancel_check=cancel_check,
                        generation_config=generation_config,
                        attempt_no=attempt_no,
                        mode='fast',
                    )
                    futures[fut] = (slot, doc, attempt_no)
                    slot_cursor += 1

                if not futures:
                    continue

                for fut in as_completed(futures):
                    slot, doc, attempt_no = futures[fut]
                    try:
                        result = fut.result()
                    except CancelledError:
                        stopped_reason = 'cancelled'
                        break
                    except BudgetExceeded as e:
                        stopped_reason = f'budget exceeded: {e}'
                        if progress_cb:
                            ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
                            progress_cb(
                                min(0.94, ratio), stopped_reason,
                                len(questions), len(rejected_records),
                            )
                        break
                    except Exception as e:
                        import traceback
                        result = SlotResult(
                            slot_id=slot['slot_id'],
                            chosen=None,
                            reject_log=[reject_mod.make(
                                'orchestrator_error',
                                stage='orchestrator',
                                attempt=attempt_no,
                                slot_id=slot['slot_id'],
                                message=f'{e}\n{traceback.format_exc()[:300]}',
                            )],
                        )
                    _handle_slot_result(slot, doc, attempt_no, result)
                    if len(questions) >= target:
                        break

        if stopped_reason == 'cancelled' and progress_cb:
            ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
            progress_cb(min(0.95, ratio), 'cancelled by user',
                        len(questions), len(rejected_records))

        if progress_cb:
            progress_cb(0.95, 'finalizing question bank...',
                        len(questions), len(rejected_records))

        render_result = None
        if out_dir and questions:
            if progress_cb:
                progress_cb(0.98, 'rendering visuals...',
                            len(questions), len(rejected_records))
            render_result = self.renderer.run(
                RenderRequest(records=questions, out_dir=out_dir)
            )

        if progress_cb:
            status_msg = 'cancelled' if stopped_reason == 'cancelled' else (
                'done' if len(questions) >= target else 'done partial'
            )
            progress_cb(1.0, status_msg, len(questions), len(rejected_records))

        return {
            'questions': questions,
            'rejected': rejected_records,
            'blueprint_summary': plan_summary,
            'cost': get_tracker().report(),
            'render_result': render_result,
            'stopped_reason': stopped_reason,
            'reject_summary': reject_mod.summarize(rejected_records),
            'mode': 'fast',
            'attempts': {
                'total_slot_attempts': slot_cursor,
                'max_total_attempts': max_total_attempts,
                'per_slot': slot_attempt_counts,
                'parallel_workers': workers,
            },
        }

    def _run_fast_batch_until_target(
        self,
        *,
        valid_slots: List[Tuple[Dict[str, Any], Dict[str, Any]]],
        dataset: Dict[str, Any],
        target: int,
        num_samples: int,
        use_nli: bool,
        out_dir: Optional[str],
        progress_cb: Optional[ProgressCallback],
        plan_summary: Dict[str, Any],
        cancel_check: Optional[CancelCheck],
        generation_config: Optional[GenerationConfig],
        rejected_records: List[Dict[str, Any]],
        max_total_attempts: int,
        slot_attempt_counts: Dict[str, int],
        slot_used_chunks: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """Fast Mode batch generation: many slots per LLM call, deterministic gates after."""
        questions: List[Dict[str, Any]] = []
        accepted_refs: List[Dict[str, str]] = []
        stopped_reason: Optional[str] = None
        slot_cursor = 0
        terminal_slots: set[str] = set()
        batch_size = max(1, int(cfg.FAST_BATCH_SIZE or 1))

        def _was_cancelled() -> bool:
            try:
                return bool(cancel_check and cancel_check())
            except Exception:
                return False

        def _reject(slot: Dict[str, Any], result: SlotResult) -> None:
            fmt_resp = self.formatter.run(FormatRejectedRequest(
                slot=slot, slot_result=result,
            ))
            rejected_records.append(fmt_resp.record)

        def _accept_or_reject(
            slot: Dict[str, Any],
            doc: Dict[str, Any],
            attempt_no: int,
            result: SlotResult,
        ) -> None:
            base_slot_id = slot.get('_base_slot_id') or slot.get('slot_id', '')
            if result.chosen:
                if accepted_refs and self._is_duplicate_question(result.chosen, accepted_refs):
                    duplicate_result = SlotResult(
                        slot_id=slot['slot_id'],
                        chosen=None,
                        reject_log=[reject_mod.make(
                            'duplicate',
                            stage='validator',
                            attempt=attempt_no,
                            slot_id=slot['slot_id'],
                            message='duplicate with previously accepted in batch run',
                            action='skip_candidate',
                        )],
                        attempts=result.attempts,
                    )
                    if attempt_no >= cfg.MAX_SLOT_ATTEMPTS:
                        _reject(slot, duplicate_result)
                        terminal_slots.add(base_slot_id)
                    return

                fmt_resp = self.formatter.run(FormatAcceptedRequest(
                    slot=slot, candidate=result.chosen, doc=doc,
                    attempts=result.attempts,
                ))
                format_issues = record_option_text_issues(fmt_resp.record)
                if format_issues:
                    _reject(slot, SlotResult(
                        slot_id=slot['slot_id'],
                        chosen=None,
                        reject_log=[reject_mod.make(
                            'format_error',
                            stage='formatter',
                            attempt=attempt_no,
                            slot_id=slot['slot_id'],
                            message=f'final formatted sanity: {format_issues}',
                            action='skip_candidate',
                        )],
                        attempts=result.attempts,
                    ))
                    terminal_slots.add(base_slot_id)
                    return

                questions.append(fmt_resp.record)
                accepted_refs.append(self._accepted_question_ref(result.chosen))
                terminal_slots.add(base_slot_id)
                return

            will_retry = (
                attempt_no < cfg.MAX_SLOT_ATTEMPTS
                and not _was_cancelled()
                and any(
                    reject_mod.coerce(e).get('reason_code')
                    in (
                        reject_mod.CONTEXT_REPAIRABLE_CODES
                        | reject_mod.REPAIRABLE_DISTRACTOR_CODES
                        | reject_mod.REPAIRABLE_WRITER_CODES
                    )
                    for e in result.reject_log
                )
            )
            if not will_retry:
                _reject(slot, result)
                terminal_slots.add(base_slot_id)

        while (
            len(questions) < target
            and valid_slots
            and not stopped_reason
            and _within_total_attempt_limit(slot_cursor, max_total_attempts)
        ):
            if _was_cancelled():
                stopped_reason = 'cancelled'
                break
            if len(terminal_slots) >= len(valid_slots):
                stopped_reason = None if len(questions) >= target else 'no more retryable slots'
                break

            batch: List[Tuple[Dict[str, Any], Dict[str, Any], str, int]] = []
            skipped_this_pass = 0
            while (
                len(batch) < batch_size
                and _within_total_attempt_limit(slot_cursor, max_total_attempts)
            ):
                base_slot, doc = valid_slots[slot_cursor % len(valid_slots)]
                base_slot_id = base_slot.get('slot_id', '')
                if base_slot_id in terminal_slots:
                    slot_cursor += 1
                    skipped_this_pass += 1
                    if skipped_this_pass > len(valid_slots) * 2:
                        break
                    continue

                attempt_no = slot_attempt_counts.get(base_slot_id, 0) + 1
                if attempt_no > cfg.MAX_SLOT_ATTEMPTS:
                    terminal_slots.add(base_slot_id)
                    slot_cursor += 1
                    continue

                slot_attempt_counts[base_slot_id] = attempt_no
                slot = dict(base_slot)
                slot['_base_slot_id'] = base_slot_id
                if attempt_no > 1:
                    slot['slot_id'] = f'{base_slot_id}_r{attempt_no:02d}'

                used_chunks = slot_used_chunks.setdefault(base_slot_id, [])
                context, chunk_ids, ctx_action = expand_context(
                    dataset, base_slot, attempt_no,
                )
                if ctx_action in {'context_missing', 'context_too_noisy'} or not context.strip():
                    result = SlotResult(
                        slot_id=slot['slot_id'],
                        chosen=None,
                        reject_log=[reject_mod.make(
                            ctx_action if ctx_action in {'context_missing', 'context_too_noisy'} else 'context_missing',
                            stage='context_selection',
                            attempt=attempt_no,
                            slot_id=slot['slot_id'],
                            message=f'clean context unavailable for doc_id={base_slot.get("doc_id", "")}',
                            action='expand_context' if attempt_no < cfg.MAX_SLOT_ATTEMPTS else 'fail_slot',
                            selected_chunk_ids=chunk_ids,
                        )],
                        attempts=attempt_no,
                    )
                    _accept_or_reject(slot, doc, attempt_no, result)
                    slot_cursor += 1
                    continue

                slot['selected_chunk_ids'] = chunk_ids
                slot['selected_context_ids'] = chunk_ids
                slot['context_selection_action'] = ctx_action
                slot['existing_question_spans'] = self._existing_question_spans_for_context(
                    dataset, base_slot, chunk_ids,
                )
                for cid in chunk_ids:
                    if cid and cid not in used_chunks:
                        used_chunks.append(cid)

                batch.append((slot, doc, context, attempt_no))
                slot_cursor += 1

            if not batch:
                continue

            if progress_cb:
                ratio = 0.02 + 0.92 * (len(questions) / max(1, target))
                progress_cb(
                    min(0.94, ratio),
                    (
                        f'accepted {len(questions)}/{target}; fast batch '
                        f'{len(batch)} slots/call; '
                        f'{_attempts_progress_text(slot_cursor, max_total_attempts)}'
                    ),
                    len(questions),
                    len(rejected_records),
                )

            try:
                batch_map = self.batch_generator.generate_batch(
                    [(slot, context) for slot, _doc, context, _attempt in batch]
                )
            except BudgetExceeded as e:
                stopped_reason = f'budget exceeded: {e}'
                break
            except Exception as e:
                batch_map = {}
                batch_error = str(e)
            else:
                batch_error = ''

            for slot, doc, context, attempt_no in batch:
                if len(questions) >= target:
                    break
                candidates = batch_map.get(slot['slot_id']) or []
                reject_log: List[Any] = []
                if not candidates:
                    reject_log.append(reject_mod.make(
                        'generation_parse_error',
                        stage='generator',
                        attempt=attempt_no,
                        slot_id=slot['slot_id'],
                        message=batch_error or 'batch generator returned no candidate for slot',
                        action='regenerate',
                    ))
                    result = SlotResult(
                        slot_id=slot['slot_id'],
                        chosen=None,
                        reject_log=reject_log,
                        attempts=attempt_no,
                    )
                    _accept_or_reject(slot, doc, attempt_no, result)
                    continue

                scored = self._evaluate_candidates(
                    candidates, context, slot, reject_log,
                    attempt_no=attempt_no,
                )
                if use_nli and len(scored) > 1:
                    try:
                        scored = filter_by_nli(scored, context)
                    except Exception as exc:
                        reject_log.append(reject_mod.make(
                            'unknown', stage='validator', attempt=attempt_no,
                            slot_id=slot['slot_id'], message=f'NLI error: {exc}',
                        ))

                scored = self._final_quality_filter(
                    scored, reject_log,
                    attempt_no=attempt_no,
                    slot_id=slot['slot_id'],
                )
                if scored:
                    scored.sort(key=lambda c: (
                        0 if c.get('_verification', {}).get('verified') is True
                        else (2 if c.get('_verifier_errored') else 1),
                        -(c.get('_quality') or 0),
                        -(c.get('_grounding') or 0),
                    ))
                    result = SlotResult(
                        slot_id=slot['slot_id'],
                        chosen=scored[0],
                        reject_log=reject_log,
                        attempts=attempt_no,
                    )
                else:
                    result = SlotResult(
                        slot_id=slot['slot_id'],
                        chosen=None,
                        reject_log=reject_log,
                        attempts=attempt_no,
                    )
                _accept_or_reject(slot, doc, attempt_no, result)

        if progress_cb:
            progress_cb(0.95, 'finalizing question bank...',
                        len(questions), len(rejected_records))

        render_result = None
        if out_dir and questions:
            if progress_cb:
                progress_cb(0.98, 'rendering visuals...',
                            len(questions), len(rejected_records))
            render_result = self.renderer.run(
                RenderRequest(records=questions, out_dir=out_dir)
            )

        if progress_cb:
            status_msg = 'cancelled' if stopped_reason == 'cancelled' else (
                'done' if len(questions) >= target else 'done partial'
            )
            progress_cb(1.0, status_msg, len(questions), len(rejected_records))

        return {
            'questions': questions,
            'rejected': rejected_records,
            'blueprint_summary': plan_summary,
            'cost': get_tracker().report(),
            'render_result': render_result,
            'stopped_reason': stopped_reason,
            'reject_summary': reject_mod.summarize(rejected_records),
            'mode': 'fast',
            'attempts': {
                'total_slot_attempts': slot_cursor,
                'max_total_attempts': max_total_attempts,
                'per_slot': slot_attempt_counts,
                'batch_size': batch_size,
            },
        }

    def run_full_pipeline(
        self, pdf_path: str, num_questions: int,
        target_chars: int = 1000, chunk_page_threshold: int = 100,
        force_chunk: bool = False, num_samples: int = cfg.NUM_SAMPLES_PER_SLOT,
        use_nli: bool = False, seed: int = 42,
        out_dir: Optional[str] = None,
        progress_cb: Optional[ProgressCallback] = None,
        mode: str = cfg.DEFAULT_GENERATION_MODE,
    ) -> Dict[str, Any]:
        if progress_cb:
            progress_cb(0.0, 'parsing PDF...', 0, 0)
        ing_resp: IngestionResponse = self.ingest(
            pdf_path, target_chars=target_chars,
            chunk_page_threshold=chunk_page_threshold, force_chunk=force_chunk,
        )
        if ing_resp.error:
            raise RuntimeError(f'Ingestion failed: {ing_resp.error}')
        if ing_resp.num_chunks == 0:
            raise RuntimeError('Ingestion: 0 chunks parsed')

        result = self.run(
            dataset=ing_resp.dataset, num_questions=num_questions,
            num_samples=num_samples, use_nli=use_nli, seed=seed,
            out_dir=out_dir, progress_cb=progress_cb,
            mode=mode,
        )
        result['source_name'] = ing_resp.source_name
        result['num_chunks'] = ing_resp.num_chunks
        return result

    # ==================================================================
    # Internal: per-slot processing
    # ==================================================================

    def _process_slot(
        self, slot: Dict[str, Any], context: str, num_samples: int,
        existing_questions: Optional[List[str]] = None,
        use_nli: bool = False,
        cancel_check: Optional[CancelCheck] = None,
        generation_config: Optional[GenerationConfig] = None,
        attempt_no: int = 1,
        mode: str = 'fast',
    ) -> SlotResult:
        """Slot pipeline: Write → Distract → Verify → Critic → (Refine?) → pick best."""
        if (mode or 'fast').lower() == 'fast':
            return self._process_slot_fast(
                slot, context, num_samples,
                existing_questions=existing_questions,
                use_nli=use_nli,
                cancel_check=cancel_check,
                attempt_no=attempt_no,
            )

        reject_log: List[Any] = []
        existing_questions = existing_questions or []
        slot_id = slot['slot_id']

        def _check_cancel() -> None:
            try:
                if cancel_check and cancel_check():
                    raise CancelledError()
            except CancelledError:
                raise
            except Exception:
                pass

        # Convert pre-existing reject_log entries (strings or dicts) into a
        # text feedback block the writer can consume.
        def _writer_feedback(history: List[Any]) -> List[str]:
            out: List[str] = []
            for entry in history[-8:]:
                ent = reject_mod.coerce(entry, slot_id=slot_id)
                msg = ent.get('message') or ent.get('reason_code') or ''
                out.append(msg[:200])
            return out

        for attempt in range(1, self.repair_attempts + 2):
            _check_cancel()
            # ---- Stage 1: Write (stem + answer + reasoning) ----
            w_resp: WriteResponse = self.writer.run(WriteRequest(
                slot=slot, context=context, num_samples=num_samples,
                feedback=_writer_feedback(reject_log),
            ))
            if not w_resp.candidates:
                reject_log.append(reject_mod.make(
                    'writer_empty',
                    stage='writer',
                    attempt=attempt,
                    slot_id=slot_id,
                    message=f'writer trả 0 candidate (errors={w_resp.errors})',
                    action='retry_writer',
                ))
                continue

            # ---- Stage 2-4: agent repair loop per candidate ----
            scored: List[Dict[str, Any]] = []
            for cand in w_resp.candidates:
                _check_cancel()
                repaired = self._repair_candidate_through_agents(
                    cand, context, slot, reject_log, attempt,
                    cancel_check=cancel_check,
                )
                if repaired:
                    scored.append(repaired)

            # NLI tiebreaker
            if use_nli and len(scored) > 1:
                try:
                    scored = filter_by_nli(scored, context)
                except Exception as e:
                    reject_log.append(reject_mod.make(
                        'unknown', stage='nli', attempt=attempt,
                        slot_id=slot_id, message=f'NLI error: {e}',
                    ))

            # Anti-dup vs accepted questions
            if existing_questions and scored:
                deduped: List[Dict[str, Any]] = []
                for c in scored:
                    if self._is_duplicate_question(c, existing_questions):
                        reject_log.append(reject_mod.make(
                            'duplicate',
                            stage='dedup',
                            attempt=attempt,
                            slot_id=slot_id,
                            message=(
                                'duplicate with previously accepted: '
                                f'{c.get("question_text", "")[:120]}'
                            ),
                            action='fail_slot',
                        ))
                        continue
                    deduped.append(c)
                scored = deduped

            if scored:
                scored.sort(key=lambda c: (
                    0 if c['_verification']['verified'] is True
                    else (2 if c.get('_verifier_errored') else 1),
                    -(c.get('_quality') or 0),
                    -(c.get('_grounding') or 0),
                ))
                return SlotResult(
                    slot_id=slot_id, chosen=scored[0],
                    reject_log=reject_log, attempts=attempt,
                )

        return SlotResult(
            slot_id=slot_id, chosen=None,
            reject_log=reject_log, attempts=self.repair_attempts + 1,
        )

    def _process_slot_fast(
        self,
        slot: Dict[str, Any],
        context: str,
        num_samples: int,
        existing_questions: Optional[List[Dict[str, str]]] = None,
        use_nli: bool = False,
        cancel_check: Optional[CancelCheck] = None,
        attempt_no: int = 1,
    ) -> SlotResult:
        """Fast path: one full-MCQ generator call, then deterministic gates.

        No DistractorAgent, RefinerAgent, or mandatory CriticAgent is used.
        LLM judge is reached only inside _evaluate_candidates when fast-accept
        cannot decide.
        """
        reject_log: List[Any] = []
        existing_questions = existing_questions or []
        slot_id = slot['slot_id']

        try:
            if cancel_check and cancel_check():
                raise CancelledError()
        except CancelledError:
            raise
        except Exception:
            pass

        samples = max(1, int(num_samples or cfg.FAST_NUM_SAMPLES_PER_SLOT))
        if samples > cfg.FAST_NUM_SAMPLES_PER_SLOT:
            samples = cfg.FAST_NUM_SAMPLES_PER_SLOT

        g_resp: GenerateResponse = self.generator.run(GenerateRequest(
            slot=slot,
            context=context,
            num_samples=samples,
        ))
        if not g_resp.candidates:
            error_blob = f'generator returned 0 valid candidates (errors={g_resp.errors})'
            code = reject_mod.classify(error_blob)
            if code == 'unknown':
                code = 'generation_parse_error'
            action = 'regenerate'
            if code in {'bad_distractors', 'distractor_validator_failed', 'explanation_low_quality'}:
                action = 'repair'
            elif code in {'grounding_low', 'quote_mismatch', 'context_missing'}:
                action = 'expand_context'
            reject_log.append(reject_mod.make(
                code,
                stage='validator' if code != 'generation_parse_error' else 'generator',
                attempt=attempt_no,
                slot_id=slot_id,
                message=error_blob,
                action=action,
            ))
            return SlotResult(slot_id=slot_id, chosen=None,
                              reject_log=reject_log, attempts=attempt_no)

        scored = self._evaluate_candidates(
            g_resp.candidates, context, slot, reject_log,
            attempt_no=attempt_no,
        )

        if use_nli and len(scored) > 1:
            try:
                scored = filter_by_nli(scored, context)
            except Exception as exc:
                reject_log.append(reject_mod.make(
                    'unknown', stage='validator', attempt=attempt_no,
                    slot_id=slot_id, message=f'NLI error: {exc}',
                ))

        scored = self._final_quality_filter(
            scored, reject_log, attempt_no=attempt_no, slot_id=slot_id,
        )

        if existing_questions and scored:
            deduped: List[Dict[str, Any]] = []
            for cand in scored:
                if self._is_duplicate_question(cand, existing_questions):
                    reject_log.append(reject_mod.make(
                        'duplicate',
                        stage='validator',
                        attempt=attempt_no,
                        slot_id=slot_id,
                        message=(
                            'duplicate with previously accepted: '
                            f'{cand.get("question_text", "")[:120]}'
                        ),
                        action='fail_slot',
                    ))
                    continue
                deduped.append(cand)
            scored = deduped

        if not scored:
            return SlotResult(slot_id=slot_id, chosen=None,
                              reject_log=reject_log, attempts=attempt_no)

        scored.sort(key=lambda c: (
            0 if c.get('_verification', {}).get('verified') is True
            else (2 if c.get('_verifier_errored') else 1),
            -(c.get('_quality') or 0),
            -(c.get('_grounding') or 0),
        ))
        return SlotResult(
            slot_id=slot_id,
            chosen=scored[0],
            reject_log=reject_log,
            attempts=attempt_no,
        )

    def _repair_candidate_through_agents(
        self,
        candidate: Dict[str, Any],
        context: str,
        slot: Dict[str, Any],
        reject_log: List[Any],
        writer_attempt: int,
        cancel_check: Optional[CancelCheck] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run Distractor -> Verify -> Critic with targeted backtracking.

        If the failure is caused by options/distractors, retry only the
        DistractorAgent with critic/verifier feedback. If the failure is in the
        stem, answer, source quote, or Bloom target, return to the outer writer
        loop so QuestionWriterAgent receives the feedback and rewrites.
        """
        base_candidate = dict(candidate)
        repair_feedback: List[str] = []
        slot_id = slot['slot_id']
        max_rounds = max(1, self.repair_attempts + 1)

        for repair_round in range(1, max_rounds + 1):
            try:
                if cancel_check and cancel_check():
                    raise CancelledError()
            except CancelledError:
                raise
            except Exception:
                pass
            d_resp: DistractorResponse = self.distractor.run(
                DistractorRequest(
                    candidate=base_candidate,
                    slot=slot,
                    context=context,
                    feedback=repair_feedback[-6:],
                )
            )
            if len(d_resp.distractors) != 3:
                msg = (
                    f'distractor agent fail: got {len(d_resp.distractors)} '
                    f'(err={d_resp.error})'
                )
                reject_log.append(reject_mod.make(
                    'bad_distractors',
                    stage='distractor',
                    attempt=writer_attempt,
                    slot_id=slot_id,
                    message=msg,
                    action='retry_distractor' if repair_round < max_rounds else 'route_writer',
                ))
                repair_feedback.append(msg)
                continue

            current = dict(base_candidate)
            current['distractors'] = d_resp.distractors
            current['_slot_difficulty_target'] = slot['difficulty_target']

            log_start = len(reject_log)
            scored = self._evaluate_candidates([current], context, slot, reject_log,
                                               attempt_no=writer_attempt)
            scored = self._maybe_refine(scored, context, slot, reject_log,
                                        attempt_no=writer_attempt)
            scored = self._final_quality_filter(scored, reject_log,
                                                attempt_no=writer_attempt,
                                                slot_id=slot_id)

            if scored:
                scored.sort(key=lambda c: (
                    0 if c.get('_verification', {}).get('verified') is True
                    else (2 if c.get('_verifier_errored') else 1),
                    -(c.get('_quality') or 0),
                    -(c.get('_grounding') or 0),
                ))
                return scored[0]

            new_entries = reject_log[log_start:]
            if not new_entries:
                fallback = reject_mod.make(
                    'unknown', stage='evaluate', attempt=writer_attempt,
                    slot_id=slot_id,
                    message='candidate rejected without explicit verifier/critic reason',
                )
                reject_log.append(fallback)
                new_entries = [fallback]

            route = self._repair_route_for_feedback(new_entries)
            for ent in new_entries:
                ent_dict = reject_mod.coerce(ent, slot_id=slot_id)
                msg = ent_dict.get('message') or ent_dict.get('reason_code', '')
                repair_feedback.append(msg[:200])
            if route == 'distractor':
                if repair_round < max_rounds:
                    reject_log.append(reject_mod.make(
                        'bad_distractors',
                        stage='orchestrator',
                        attempt=writer_attempt,
                        slot_id=slot_id,
                        message='routing feedback back to DistractorAgent',
                        action='retry_distractor',
                    ))
                    continue
                reject_log.append(reject_mod.make(
                    'max_attempts_exceeded',
                    stage='orchestrator',
                    attempt=writer_attempt,
                    slot_id=slot_id,
                    message='distractor repair exhausted',
                    action='give_up_candidate',
                ))
            else:
                reject_log.append(reject_mod.make(
                    'unknown',
                    stage='orchestrator',
                    attempt=writer_attempt,
                    slot_id=slot_id,
                    message='routing feedback back to QuestionWriterAgent',
                    action='route_writer',
                ))
            return None

        return None

    @staticmethod
    def _repair_route_for_feedback(feedback: List[Any]) -> str:
        # Accept structured dicts or raw strings.
        codes: List[str] = []
        text_blob: List[str] = []
        for entry in feedback:
            if isinstance(entry, dict):
                if entry.get('reason_code'):
                    codes.append(entry['reason_code'])
                text_blob.append(str(entry.get('message') or ''))
            else:
                text_blob.append(str(entry))

        if codes:
            if any(c in reject_mod.REPAIRABLE_DISTRACTOR_CODES for c in codes):
                return 'distractor'
            if any(c in reject_mod.REPAIRABLE_WRITER_CODES
                       | reject_mod.CONTEXT_REPAIRABLE_CODES for c in codes):
                return 'writer'

        text = ' | '.join(text_blob).lower()
        writer_markers = (
            'verifier=false', 'grounding', 'quote', 'local contradiction',
            'bloom_alignment', 'clarity',
            'duplicate with previously accepted', 'unsupported stem',
        )
        distractor_markers = (
            'distractor_validator', 'option_text_sanity', 'iwf_',
            'multi_answer', 'answer_uniqueness', 'uniqueness',
            'distractor_plausibility', 'duplicate distractor',
            'format_consistency',
        )
        if any(marker in text for marker in distractor_markers):
            return 'distractor'
        if any(marker in text for marker in writer_markers):
            return 'writer'
        return 'writer'

    def _evaluate_candidates(
        self, candidates: List[Dict[str, Any]], context: str,
        slot: Dict[str, Any], reject_log: List[Any],
        attempt_no: int = 1,
    ) -> List[Dict[str, Any]]:
        """Phase Verifier (sequential, no LLM, early-exit) → Critic (parallel LLM)."""
        slot_id = slot.get('slot_id', '')
        verified: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for c in candidates:
            v_resp: VerifyResponse = self.verifier.run(
                VerifyRequest(candidate=c, slot=slot),
            )
            if v_resp.rejected:
                code = reject_mod.classify(v_resp.reject_reason)
                if code == 'unknown' and (v_resp.reject_reason or '').startswith('format_error'):
                    code = 'format_error'
                if code == 'unknown' and (v_resp.reject_reason or '').startswith('bad_distractors'):
                    code = 'bad_distractors'
                stage = 'validator' if code in {
                    'format_error', 'bad_distractors', 'distractor_validator_failed',
                    'explanation_low_quality',
                } else 'verifier'
                reject_log.append(reject_mod.make(
                    code if code != 'unknown' else 'verifier_failed',
                    stage=stage,
                    attempt=attempt_no,
                    slot_id=slot_id,
                    message=v_resp.reject_reason,
                    action=(
                        'regenerate'
                        if code in {'verifier_failed', 'duplicate_question'}
                        else 'repair'
                    ),
                ))
                continue
            candidate_patch = v_resp.annotations.pop('_candidate_patch', None)
            if isinstance(candidate_patch, dict):
                c.update(candidate_patch)
            verified.append((c, v_resp.annotations))

        if not verified:
            return []

        passed: List[Dict[str, Any]] = []
        to_critic: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for c, v_ann in verified:
            fast_ann = self._fast_accept_annotations(c, v_ann, context, slot)
            if fast_ann:
                c.update(v_ann)
                c.update(fast_ann)
                passed.append(c)
            else:
                to_critic.append((c, v_ann))

        if not to_critic:
            return passed

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='critic') as pool:
            futures = []
            for c, v_ann in to_critic:
                fut = pool.submit(
                    self.critic.run,
                    CriticRequest(
                        candidate=c, context=context,
                        topic=slot.get('topic', ''),
                        cognitive_level=slot['cognitive_level'],
                    ),
                )
                futures.append((c, v_ann, fut))

            for c, v_ann, fut in futures:
                try:
                    cr_resp: CriticResponse = fut.result()
                except Exception as e:
                    reject_log.append(reject_mod.make(
                        'orchestrator_error', stage='critic',
                        attempt=attempt_no, slot_id=slot_id,
                        message=f'critic error: {e}',
                    ))
                    continue
                if cr_resp.rejected:
                    code = reject_mod.classify(cr_resp.reject_reason)
                    if code == 'unknown':
                        code = 'grounding_low' if 'grounding' in (cr_resp.reject_reason or '').lower() else 'quality_low'
                    reject_log.append(reject_mod.make(
                        code, stage='judge',
                        attempt=attempt_no, slot_id=slot_id,
                        message=cr_resp.reject_reason,
                        score=cr_resp.annotations.get('_grounding') if 'grounding' in code else cr_resp.annotations.get('_quality'),
                        action='expand_context' if code in {'grounding_low', 'quote_mismatch'} else 'regenerate',
                    ))
                    continue
                c.update(v_ann)
                c.update(cr_resp.annotations)
                passed.append(c)
        return passed

    def _fast_accept_annotations(
        self,
        candidate: Dict[str, Any],
        verifier_annotations: Dict[str, Any],
        context: str,
        slot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Skip LLM critic for low-risk symbolic candidates.

        Deterministic gates still run: symbolic verification, validator, quote
        support, local contradiction, and basic answer shape.
        """
        if not cfg.FAST_ACCEPT_VERIFIED_SHORT_ANSWER:
            return {}
        verification = verifier_annotations.get('_verification') or {}
        verified = verification.get('verified')
        engine = verification.get('engine')
        grounded_unverified = (
            cfg.FAST_ACCEPT_GROUNDED_UNVERIFIED
            and verified is None
            and engine == 'none'
        )
        if verified is not True and not grounded_unverified:
            return {}

        answer = str(candidate.get('answer_text', '') or '').strip()
        if verified is True and len(answer) > cfg.FAST_ACCEPT_ANSWER_MAX_CHARS:
            return {}
        if grounded_unverified and len(answer) > cfg.FAST_ACCEPT_CONCEPTUAL_ANSWER_MAX_CHARS:
            return {}

        contradiction = gj.directional_contradiction(context, candidate)
        if contradiction:
            return {}
        if not str(candidate.get('answer_explanation_text') or '').strip():
            return {}

        quote = candidate.get('source_quote_text', '')
        aligned_quote = gj.find_supported_quote(quote, context) if quote else None
        if not aligned_quote:
            aligned_quote = self._fallback_supported_quote(context, candidate)
        if not aligned_quote:
            return {}

        traits = {
            'clarity': {
                'score': 0.8,
                'rationale': (
                    'Fast-path: symbolic verification passed and the answer format is concise.'
                    if verified is True else
                    'Fast-path: rule validation passed and the source quote is grounded.'
                ),
            },
            'cognitive_depth': {
                'score': 0.8,
                'rationale': (
                    'Fast-path: deterministic verifier confirms the mathematical target.'
                    if verified is True else
                    'Fast-path: accepted as a grounded conceptual item without a symbolic verifier.'
                ),
            },
            'bloom_alignment': {
                'score': 0.8,
                'rationale': (
                    'Fast-path: verified computational item matches a non-conceptual blueprint slot.'
                    if verified is True else
                    'Fast-path: grounded conceptual item from the selected clean context.'
                ),
            },
            'distractor_plausibility': {
                'score': 0.75,
                'rationale': 'Fast-path: distractor validator passed; no LLM rubric call was made.',
            },
            'answer_uniqueness': {
                'score': 1.0,
                'rationale': (
                    'Fast-path: verifier rejected no distractor as another correct answer.'
                    if verified is True else
                    'Fast-path: rule validator found one answer and three unique alternatives.'
                ),
            },
        }
        return {
            '_grounding': 1.0,
            '_quote_in_context': True,
            '_unsupported_stem_numbers': gj.unsupported_stem_numbers(context, candidate),
            '_distractor_context_trace': gj.distractor_context_trace(context, candidate),
            '_quality': cfg.FAST_ACCEPT_HEURISTIC_QUALITY,
            '_quality_traits': traits,
            '_bloom_alignment': traits['bloom_alignment']['score'],
            '_critic_skipped': (
                'verified_short_answer_fast_path'
                if verified is True else 'grounded_rule_valid_fast_path'
            ),
            'source_quote_text': aligned_quote,
        }

    @staticmethod
    def _fallback_supported_quote(context: str, candidate: Dict[str, Any]) -> str:
        """Pick an exact short context span when the model quote is too fuzzy."""
        raw_text = context or ''
        if not raw_text.strip():
            return ''
        qa = OrchestratorAgent._fold_for_signature(' '.join([
            str(candidate.get('question_text') or ''),
            str(candidate.get('answer_text') or ''),
            str(candidate.get('answer_explanation_text') or ''),
        ]))
        qa_raw = ' '.join([
            str(candidate.get('question_text') or ''),
            str(candidate.get('answer_text') or ''),
            str(candidate.get('answer_explanation_text') or ''),
        ])
        qa_has_integral = bool(re.search(r'\\int|∫', qa_raw)) or 'tich phan' in qa
        preferred = (
            'tich phan', 'nguyen ham', 'dien tich', 'hinh phang',
            'van toc', 'luu luong', 'dien luong', 'do thi',
            'cong thuc', 'quang duong',
        )
        lines: List[str] = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.match(r'(?i)^\s*(source quote candidates|clean context text)\s*:', line):
                continue
            if line.startswith(('-', '+', '*')):
                line = line[1:].strip()
            lines.append(line)
        text = re.sub(r'\s+', ' ', raw_text).strip()
        spans = [
            s.strip(' "\'“”')
            for s in (
                lines
                + re.split(r'(?<=[.!?])\s+', text)
            )
            if 20 <= len(s.strip()) <= 260
        ]
        if not spans and len(text) >= 20:
            spans = [text[:260].strip()]
        scored: List[Tuple[int, str]] = []
        for span in spans[:24]:
            if re.match(r'(?i)^\s*(topic|chunk type|context type|title)\s*:', span):
                continue
            if re.search(r'(?i)\b(source quote candidates|clean context text)\s*:', span):
                continue
            folded = OrchestratorAgent._fold_for_signature(span)
            score = sum(2 for key in preferred if key in folded and key in qa)
            score += sum(1 for key in preferred if key in folded)
            if re.search(r'\\int|∫|=|[<>]|\d', span):
                score += 1
            if qa_has_integral and any(
                key in folded for key in ('tich phan', 'cong thuc', 'hinh phang', 'dien tich')
            ):
                score += 3
            if score > 0:
                scored.append((score, span))
        if not scored:
            return ''
        scored.sort(key=lambda item: (-item[0], len(item[1])))
        return scored[0][1]

    def _maybe_refine(
        self, candidates: List[Dict[str, Any]], context: str,
        slot: Dict[str, Any], reject_log: List[Any],
        attempt_no: int = 1,
    ) -> List[Dict[str, Any]]:
        """Với candidate có _refinable=True (quality thấp nhưng có cơ hội cứu),
        gọi RefinerAgent 1 lần với rationale từ multi-trait critic, rồi re-evaluate.

        Candidate verified=True và quality cao thì BỎ QUA refine (không tốn LLM).
        """
        slot_id = slot.get('slot_id', '')
        out: List[Dict[str, Any]] = []
        to_refine: List[Dict[str, Any]] = []
        for c in candidates:
            bloom = c.get('_bloom_alignment')
            needs_refine = (
                (c.get('_quality') or 0) < cfg.QUALITY_THRESHOLD
                or (bloom is not None and bloom < 0.7)
            )
            if c.get('_refinable') and needs_refine:
                to_refine.append(c)
            else:
                out.append(c)

        if not to_refine:
            return out

        for c in to_refine:
            try:
                r_resp: RefineResponse = self.refiner.run(RefineRequest(
                    candidate=c,
                    critique_traits=c.get('_quality_traits', {}),
                ))
            except BudgetExceeded:
                raise
            except Exception as e:
                reject_log.append(reject_mod.make(
                    'orchestrator_error', stage='refiner',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'refiner error: {e}',
                ))
                out.append(c)
                continue

            refined = r_resp.candidate
            # Carry over slot metadata + verifier_hint từ original (refiner không
            # đụng vào verifier hint để tránh phá symbolic check).
            refined['_slot_id'] = c.get('_slot_id')
            refined['_slot_difficulty_target'] = c.get('_slot_difficulty_target')
            refined['verifier_hint'] = c.get('verifier_hint')
            refined['source_quote_text'] = c.get('source_quote_text', '')
            refined['visual'] = c.get('visual')

            # Re-evaluate refined candidate
            re_scored = self._evaluate_candidates(
                [refined], context, slot, reject_log,
                attempt_no=attempt_no,
            )
            if re_scored:
                # Mark refined để debug
                re_scored[0]['_refined'] = True
                out.extend(re_scored)
            else:
                # Refine không cứu được → giữ original (vẫn pass critic ban đầu)
                bloom = c.get('_bloom_alignment')
                if (c.get('_quality') or 0) < cfg.QUALITY_THRESHOLD or (
                    bloom is not None and bloom < 0.5
                ):
                    reject_log.append(reject_mod.make(
                        'quality_low', stage='refiner',
                        attempt=attempt_no, slot_id=slot_id,
                        message='refine failed; dropping low-quality/bloom-misaligned candidate',
                        action='drop_candidate',
                    ))
                else:
                    out.append(c)
        return out

    def _final_quality_filter(
        self,
        candidates: List[Dict[str, Any]],
        reject_log: List[Any],
        attempt_no: int = 1,
        slot_id: str = '',
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for c in candidates:
            q = c.get('_quality')
            g = c.get('_grounding')
            bloom = c.get('_bloom_alignment')
            traits = c.get('_quality_traits') or {}
            clarity = traits.get('clarity', {}).get('score', 1.0)
            plausibility = traits.get('distractor_plausibility', {}).get('score', 1.0)
            uniq = traits.get('answer_uniqueness', {}).get('score', 1.0)
            if c.get('_verifier_errored'):
                reject_log.append(reject_mod.make(
                    'verifier_failed', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'verifier errored + quality={q}', score=q,
                ))
                continue
            # Slightly soften the previous +0.05 quality buffer — math candidates
            # at threshold often shouldn't be rejected just for being "close".
            if q is not None and q < cfg.QUALITY_THRESHOLD:
                reject_log.append(reject_mod.make(
                    'quality_low', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'quality={q:.2f} < {cfg.QUALITY_THRESHOLD}', score=q,
                ))
                continue
            if g is not None and g < cfg.GROUNDING_THRESHOLD:
                reject_log.append(reject_mod.make(
                    'grounding_low', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'grounding={g:.2f} < {cfg.GROUNDING_THRESHOLD}', score=g,
                    action='expand_context',
                ))
                continue
            if bloom is not None and bloom < 0.65:
                reject_log.append(reject_mod.make(
                    'quality_low', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'bloom_alignment={bloom:.2f} < 0.65', score=bloom,
                ))
                continue
            if clarity < 0.55:
                reject_log.append(reject_mod.make(
                    'quality_low', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'clarity={clarity:.2f} < 0.55', score=clarity,
                ))
                continue
            if plausibility < 0.55:
                reject_log.append(reject_mod.make(
                    'bad_distractors', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'distractor_plausibility={plausibility:.2f} < 0.55',
                    score=plausibility, action='retry_distractor',
                ))
                continue
            if uniq < 0.6:
                reject_log.append(reject_mod.make(
                    'multi_answer', stage='final',
                    attempt=attempt_no, slot_id=slot_id,
                    message=f'answer_uniqueness={uniq:.2f} < 0.60', score=uniq,
                    action='retry_distractor',
                ))
                continue
            out.append(c)
        return out

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _existing_question_spans_for_context(
        dataset: Dict[str, Any],
        slot: Dict[str, Any],
        chunk_ids: List[str],
        limit: int = 24,
    ) -> List[str]:
        """Collect anti-copy spans from the base slot and selected context chunks."""
        spans: List[str] = []
        seen = set()

        def add_many(items: Any) -> None:
            for raw in items or []:
                text = re.sub(r'\s+', ' ', str(raw or '')).strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                spans.append(text[:500])
                if len(spans) >= limit:
                    return

        add_many(slot.get('existing_question_spans') or [])
        for cid in chunk_ids or []:
            doc = dataset.get(cid) or {}
            clean = doc.get('clean_context') if isinstance(doc.get('clean_context'), dict) else {}
            add_many(clean.get('existing_question_spans') or [])
            if len(spans) >= limit:
                break
        return spans[:limit]

    @staticmethod
    def _normalize_for_dedup(text: str) -> str:
        text = (text or '').lower()
        text = re.sub(r'[^0-9a-zA-ZÀ-ỹĐđ]+', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _fold_for_signature(text: str) -> str:
        norm = unicodedata.normalize('NFKD', text or '')
        folded = ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()
        folded = folded.replace('đ', 'd')
        return re.sub(r'\s+', ' ', folded).strip()

    @classmethod
    def _accepted_question_ref(cls, candidate: Dict[str, Any]) -> Dict[str, str]:
        return {
            'question_text': str(candidate.get('question_text') or ''),
            'answer_text': str(candidate.get('answer_text') or ''),
            'source_quote': str(candidate.get('source_quote_text') or ''),
            'core_signature': cls._core_question_signature(candidate),
            'verifier_signature': cls._verifier_question_signature(candidate),
            'verifier_value_signature': cls._verifier_value_signature(candidate),
            'verifier_value_family': cls._verifier_value_family(candidate),
        }

    @staticmethod
    def _verifier_hint(candidate: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        raw = candidate.get('verifier_hint') or candidate.get('verifier_payload') or {}
        if not isinstance(raw, dict):
            return '', {}
        vtype = str(raw.get('type') or raw.get('verifier_type') or '').strip()
        payload = raw.get('payload') if isinstance(raw.get('payload'), dict) else raw
        return vtype, payload if isinstance(payload, dict) else {}

    @classmethod
    def _normalize_verifier_expression(cls, expr: Any) -> str:
        text = str(expr or '')
        if not text.strip():
            return ''
        text = cls._fold_for_signature(text)
        text = re.sub(r'\\(?:left|right)\b', '', text)
        text = text.replace('**', '^')
        return re.sub(r'\s+', '', text)

    @staticmethod
    def _normalize_verifier_number(value: Any) -> str:
        if value is None:
            return ''
        text = str(value).strip().replace(',', '.')
        if not text:
            return ''
        try:
            number = float(text)
        except Exception:
            return ''
        if abs(number - round(number)) < 1e-10:
            return str(int(round(number)))
        return f'{number:.10g}'

    @classmethod
    def _verifier_question_signature(cls, candidate: Dict[str, Any]) -> str:
        vtype, payload = cls._verifier_hint(candidate)
        if vtype != 'numeric_eval':
            return ''
        expr = payload.get('expr') or payload.get('expression')
        expr_norm = cls._normalize_verifier_expression(expr)
        return f'numeric_eval:expr:{expr_norm}' if expr_norm else ''

    @classmethod
    def _verifier_value_signature(cls, candidate: Dict[str, Any]) -> str:
        vtype, payload = cls._verifier_hint(candidate)
        if vtype not in {'numeric_eval', 'probability', 'counting', 'limit', 'modular'}:
            return ''
        raw = (
            payload.get('expected_numeric')
            if 'expected_numeric' in payload else payload.get('expected')
        )
        if raw is None:
            raw = payload.get('claimed_value')
        value = cls._normalize_verifier_number(raw)
        return f'{vtype}:expected:{value}' if value else ''

    @classmethod
    def _verifier_value_family(cls, candidate: Dict[str, Any]) -> str:
        core = cls._core_question_signature(candidate)
        if core.startswith('accumulation:'):
            return 'accumulation'
        if core.startswith('antiderivative_initial_condition'):
            return 'antiderivative_initial_condition'
        if core:
            return core.split(':', 1)[0]
        text = cls._fold_for_signature(' '.join([
            str(candidate.get('question_text') or ''),
            str(candidate.get('source_quote_text') or ''),
            str(candidate.get('answer_explanation_text') or ''),
        ]))
        if any(term in text for term in ('luu luong', 'be nuoc', 'quang duong', 'van toc', 'dien luong', 'dong dien')):
            return 'accumulation'
        if 'dien tich' in text and ('do thi' in text or 'hinh phang' in text):
            return 'area_between_graphs'
        if 'nguyen ham' in text:
            return 'antiderivative_initial_condition'
        return ''

    @classmethod
    def _core_question_signature(cls, candidate: Dict[str, Any]) -> str:
        text = cls._fold_for_signature(
            ' '.join([
                str(candidate.get('question_text') or ''),
                str(candidate.get('answer_text') or ''),
                str(candidate.get('answer_explanation_text') or ''),
            ])
        )
        raw = ' '.join([
            str(candidate.get('question_text') or ''),
            str(candidate.get('answer_text') or ''),
        ])
        compact_raw = re.sub(r'\s+', '', raw).lower()
        compact_text = re.sub(r'\s+', '', text)
        mentions_integral = bool(re.search(r'\\int|∫', raw)) or 'tich phan' in text
        mentions_nonnegative_function = (
            'khongam' in compact_text
            or bool(re.search(r'[fg]\s*\(\s*x\s*\)\s*(?:\\ge|>=|≥)\s*0', raw, re.I))
            or bool(re.search(r'0\s*(?:\\le|<=|≤)\s*[fg]\s*\(\s*x\s*\)', raw, re.I))
            or bool(re.search(r'[fg]\(x\)(?:\\ge|>=|≥)0', compact_raw, re.I))
            or bool(re.search(r'0(?:\\le|<=|≤)[fg]\(x\)', compact_raw, re.I))
        )
        if (
            mentions_integral
            and mentions_nonnegative_function
            and (
                any(x in text for x in (
                    'khong am', 'khong duong', 'khong nho hon 0',
                    '>= 0', 'ge 0', '\\ge 0', '≥ 0',
                ))
                or any(x in compact_text for x in ('>=0', '\\ge0', '≥0', '0<=', '0\\le', '0≤'))
            )
        ):
            return 'integral_positivity_property'
        if mentions_integral and re.search(
            r'(?:\\int|∫)\s*_\s*\{?\s*([a-zA-Z])\s*\}?\s*\^\s*\{?\s*\1\s*\}?',
            raw,
        ):
            return 'integral_zero_interval_property'
        if 'dien tich' in text and ('do thi' in text or 'hinh phang' in text):
            return 'area_between_graphs'
        if 'nguyen ham' in text and re.search(r'[fsv]\s*\(\s*0\s*\)', raw, re.I):
            if 'cos' in text:
                return 'antiderivative_initial_condition:cos'
            if 'sin' in text:
                return 'antiderivative_initial_condition:sin'
            return 'antiderivative_initial_condition'
        if re.search(r'[fsv]\s*\(\s*0\s*\)', raw, re.I) and any(x in text for x in ('cos', 'sin')):
            if 'cos' in text:
                return 'antiderivative_initial_condition:cos'
            if 'sin' in text:
                return 'antiderivative_initial_condition:sin'
            return 'antiderivative_initial_condition'
        if 'nguyen ham' in text and any(x in text for x in ('nghich bien', 'dong bien', 'cuc dai', 'cuc tieu')):
            return 'antiderivative_monotonicity'
        if 'luu luong' in text or 'be nuoc' in text:
            return 'accumulation:flow'
        if 'dien luong' in text or 'dong dien' in text:
            return 'accumulation:current'
        if 'quang duong' in text or 'van toc' in text:
            return 'accumulation:motion'
        if len(re.findall(r'\\int|∫', raw)) >= 2 and any(x in text for x in ('biet', 'cho')):
            return 'integral_additivity_or_linearity'
        if re.search(r'^\s*(?:tinh|gia tri cua)\s*(?:[a-z]\s*=\s*)?(?:\\\()?\\int', text):
            return 'bare_definite_integral'
        return ''

    @classmethod
    def _is_duplicate_question(cls, candidate: Dict[str, Any],
                               existing_questions: List[Dict[str, str]]) -> bool:
        """Strong dup detection — match khi:
        - Stem giống (jaccard ≥ 0.55 hoặc seq ≥ 0.7), HOẶC
        - Answer giống + source quote giống, HOẶC
        - Answer giống + stem một phần
        """
        stem = cls._normalize_for_dedup(candidate.get('question_text', ''))
        ans = cls._normalize_for_dedup(candidate.get('answer_text', ''))
        quote = cls._normalize_for_dedup(candidate.get('source_quote_text', ''))
        core_signature = cls._core_question_signature(candidate)
        verifier_signature = cls._verifier_question_signature(candidate)
        verifier_value_signature = cls._verifier_value_signature(candidate)
        verifier_value_family = cls._verifier_value_family(candidate)
        stem_tokens = set(stem.split())
        ans_tokens = set(ans.split()) if ans else set()
        quote_tokens = set(quote.split()) if quote else set()

        for prev in existing_questions:
            prev_stem = cls._normalize_for_dedup(prev.get('question_text', ''))
            prev_ans = cls._normalize_for_dedup(prev.get('answer_text', ''))
            prev_quote = cls._normalize_for_dedup(prev.get('source_quote', ''))
            prev_core_signature = str(prev.get('core_signature') or '')
            prev_verifier_signature = str(prev.get('verifier_signature') or '')
            prev_value_signature = str(prev.get('verifier_value_signature') or '')
            prev_value_family = str(prev.get('verifier_value_family') or '')
            both_have_numeric_verifier = bool(
                (verifier_signature or verifier_value_signature)
                and (prev_verifier_signature or prev_value_signature)
            )
            if (
                verifier_signature
                and prev_verifier_signature
                and verifier_signature == prev_verifier_signature
            ):
                return True
            if (
                verifier_value_signature
                and prev_value_signature
                and verifier_value_signature == prev_value_signature
                and verifier_value_family
                and prev_value_family
                and verifier_value_family == prev_value_family
            ):
                return True
            if (
                core_signature
                and prev_core_signature
                and core_signature == prev_core_signature
                and not both_have_numeric_verifier
            ):
                return True
            if len(stem) < 30 or len(prev_stem) < 30:
                continue

            prev_stem_tokens = set(prev_stem.split())
            stem_jaccard = (
                len(stem_tokens & prev_stem_tokens)
                / max(1, len(stem_tokens | prev_stem_tokens))
            )
            stem_seq = SequenceMatcher(None, stem, prev_stem).ratio()

            # 1. Stem trùng → duplicate
            if stem_seq >= 0.70 or stem_jaccard >= 0.55:
                return True

            # 2. Answer giống nhau (cùng công thức/giá trị)
            if prev_ans and ans:
                ans_seq = SequenceMatcher(None, ans, prev_ans).ratio()
                if ans_seq >= 0.85:
                    # Answer khớp + stem cũng tương tự → dup
                    if stem_jaccard >= 0.40 or stem_seq >= 0.55:
                        return True
                    # Answer khớp + same source quote → dup mạnh
                    if quote and prev_quote:
                        prev_q_tokens = set(prev_quote.split())
                        q_jaccard = (
                            len(quote_tokens & prev_q_tokens)
                            / max(1, len(quote_tokens | prev_q_tokens))
                        )
                        if q_jaccard >= 0.80:
                            return True
            if quote and prev_quote:
                prev_q_tokens = set(prev_quote.split())
                q_jaccard = (
                    len(quote_tokens & prev_q_tokens)
                    / max(1, len(quote_tokens | prev_q_tokens))
                )
                if q_jaccard >= 0.90 and (stem_jaccard >= 0.35 or stem_seq >= 0.50):
                    return True
        return False
