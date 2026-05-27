"""Background workers for ingestion and generation.

Both run in BackgroundTasks (anyio worker thread). Status written to
filesystem via store; clients poll GET /job/:id/status.

Concurrency note: the OrchestratorAgent is itself stateless across runs,
but `pipeline.llm_client.get_tracker()` is a shared singleton. We
`reset_tracker(...)` at the start of each generate run to give every job
its own budget window. Running two generates in parallel in the same
process is therefore not supported — UI is single-job today, and the
filesystem store has one Lock per job to keep status writes serialized.
"""
from __future__ import annotations

from collections import Counter
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline import config as cfg
from pipeline import customization as cust_mod
from pipeline import reject as reject_mod
from pipeline.agents import IngestionRequest, OrchestratorAgent, PlanResponse
from pipeline.blueprint import summary as bp_summary
from pipeline.chunk_context_builder import attach_clean_contexts, build_clean_contexts
from pipeline.llm_client import BudgetExceeded, get_tracker, reset_tracker

from . import store


# Single shared orchestrator — sub-agents are stateless and the writer/
# distractor/critic LLM call sites already manage their own concurrency.
_orchestrator: Optional[OrchestratorAgent] = None
_orchestrator_lock = threading.Lock()


def get_orchestrator() -> OrchestratorAgent:
    global _orchestrator
    with _orchestrator_lock:
        if _orchestrator is None:
            _orchestrator = OrchestratorAgent()
        return _orchestrator


# ----------------------------------------------------------------------
# Ingestion (synchronous from /upload)
# ----------------------------------------------------------------------

def run_ingestion(job_id: str, pdf_path: Path) -> Dict[str, Any]:
    """Run IngestionAgent and persist chunks. Returns result dict for caller.

    Synchronous: IngestionAgent does not call LLM, completes in seconds for
    typical PDFs. Errors are written to errors.log and surface via meta.status.
    """
    store.write_status(job_id, {
        'status': 'running',
        'progress': 0.05,
        'message': 'parsing PDF...',
        'current_agent': 'IngestionAgent',
    })
    store.update_meta(job_id, status='running')

    try:
        ing_resp = get_orchestrator().ingestion.run(IngestionRequest(
            pdf_path=str(pdf_path),
            allow_very_long=True,
        ))
    except Exception as e:
        store.append_error(job_id, f'ingestion crashed: {e}\n{traceback.format_exc()}')
        store.write_status(job_id, {
            'status': 'error',
            'progress': 0.0,
            'message': 'ingestion crashed',
            'error': str(e),
        })
        store.update_meta(job_id, status='error', error=str(e))
        return {'ok': False, 'error': str(e)}

    if ing_resp.error:
        store.append_error(job_id, f'ingestion error: {ing_resp.error}')
        store.write_status(job_id, {
            'status': 'error',
            'progress': 0.0,
            'message': 'ingestion failed',
            'error': ing_resp.error,
        })
        store.update_meta(job_id, status='error', error=ing_resp.error)
        return {'ok': False, 'error': ing_resp.error}

    store.save_chunks(job_id, ing_resp.dataset)
    clean_contexts = {
        'metadata': (ing_resp.dataset.get('metadata') or {}).get('clean_contexts_payload', {})
    }
    for chunk_id, chunk in ing_resp.dataset.items():
        if chunk_id != 'metadata' and isinstance(chunk, dict) and isinstance(chunk.get('clean_context'), dict):
            clean_contexts[chunk_id] = chunk['clean_context']
    clean_contexts['metadata']['num_contexts'] = max(0, len(clean_contexts) - 1)
    store.save_clean_contexts(job_id, clean_contexts)
    store.update_meta(
        job_id,
        status='ingested',  # waiting for plan generation/review
        num_chunks=ing_resp.num_chunks,
        source_name=ing_resp.source_name,
    )
    store.write_status(job_id, {
        'status': 'ingested',
        'progress': 0.10,
        'message': f'parsed {ing_resp.num_chunks} chunk(s); clean contexts ready',
    })
    return {'ok': True, 'num_chunks': ing_resp.num_chunks}


# ----------------------------------------------------------------------
# Generation (async via BackgroundTasks)
# ----------------------------------------------------------------------

_BLOOM_TARGETS: Dict[str, float] = {
    'Nhận biết': 0.30,
    'Thông hiểu': 0.50,
    'Vận dụng': 0.70,
    'Vận dụng cao': 0.85,
}


def _bloom_distribution(bloom_level: str, num_questions: int
                         ) -> Optional[List[Dict[str, Any]]]:
    if bloom_level == 'mixed' or bloom_level not in _BLOOM_TARGETS:
        return None
    return [{
        'cognitive_level': bloom_level,
        'difficulty_target': _BLOOM_TARGETS[bloom_level],
        'fraction': 1.0,
    }]


def _make_progress_cb(job_id: str):
    """Return a (ratio, msg, accepted, rejected) callback that writes status."""
    last_emit = [0.0]

    def cb(ratio: float, msg: str, accepted: int, rejected: int) -> None:
        now = time.time()
        # Throttle to ~3 writes/sec to avoid hammering the filesystem.
        if ratio < 1.0 and (now - last_emit[0]) < 0.33:
            return
        last_emit[0] = now
        # Read result so far so the UI sees a live reject summary mid-flight.
        partial_result = store.get_result(job_id) if ratio >= 1.0 else None
        rejected_records = (
            (partial_result or {}).get('rejected') if partial_result else []
        )
        reject_summary = reject_mod.summarize(rejected_records or [])
        status_payload: Dict[str, Any] = {
            'status': (
                'cancelled' if 'cancelled' in (msg or '').lower()
                else ('generating' if ratio < 1.0 else 'done')
            ),
            'progress': max(0.0, min(1.0, float(ratio))),
            'message': msg,
            'current_agent': _agent_from_msg(msg),
            'accepted': accepted,
            'rejected_count': rejected,
            'reject_summary': reject_summary,
            'cancel_requested': store.is_cancel_requested(job_id),
        }
        store.write_status(job_id, status_payload)

    return cb


def _agent_from_msg(msg: str) -> Optional[str]:
    """Best-effort: derive the active agent from the orchestrator message."""
    m = msg.lower()
    if 'plan' in m or 'blueprint' in m:
        return 'PlannerAgent'
    if 'generator' in m or 'fast' in m:
        return 'QuestionGeneratorAgent'
    if 'slot' in m or 'writer' in m:
        return 'QuestionWriterAgent'
    if 'distract' in m:
        return 'DistractorAgent'
    if 'critic' in m or 'rubric' in m:
        return 'LLMJudge'
    if 'verif' in m:
        return 'VerifierAgent'
    if 'refin' in m:
        return 'RefinerAgent'
    if 'format' in m:
        return 'FormatterAgent'
    if 'render' in m:
        return 'RendererAgent'
    return None

def _question_bank_summary(
    questions: List[Dict[str, Any]],
    rejected: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compact analytics for question-bank review/export screens."""
    total = len(questions) + len(rejected)
    by_topic = Counter(q.get('topic') or 'unknown' for q in questions)
    by_bloom = Counter(q.get('cognitive_level') or 'unknown' for q in questions)
    by_type = Counter(q.get('question_type') or 'single_choice' for q in questions)
    by_review = Counter(q.get('review_status') or 'pending_review' for q in questions)

    verified = [
        q for q in questions
        if (q.get('verification') or {}).get('verified') is True
    ]
    symbolic_verified = [
        q for q in verified
        if (q.get('verification') or {}).get('engine') not in (None, '', 'none')
    ]
    qualities = [
        float((q.get('judging') or {}).get('quality'))
        for q in questions
        if (q.get('judging') or {}).get('quality') is not None
    ]
    groundings = [
        float((q.get('judging') or {}).get('grounding'))
        for q in questions
        if (q.get('judging') or {}).get('grounding') is not None
    ]

    return {
        'accepted_count': len(questions),
        'rejected_count': len(rejected),
        'total_attempted': total,
        'acceptance_rate': (len(questions) / total) if total else 0.0,
        'review_queue_count': sum(
            by_review.get(status, 0)
            for status in ('pending_review', 'needs_revision')
        ),
        'approved_count': by_review.get('approved', 0),
        'needs_revision_count': by_review.get('needs_revision', 0),
        'verified_count': len(verified),
        'symbolic_verified_count': len(symbolic_verified),
        'avg_quality': (sum(qualities) / len(qualities)) if qualities else None,
        'avg_grounding': (sum(groundings) / len(groundings)) if groundings else None,
        'by_topic': dict(by_topic),
        'by_bloom': dict(by_bloom),
        'by_type': dict(by_type),
        'by_review_status': dict(by_review),
    }

def _slot_from_plan_slot(plan_slot: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a rich plan slot back to the flat slot shape orchestrator expects."""
    source = plan_slot.get('source_chunk') or {}
    qspec = plan_slot.get('question_spec') or {}
    dspec = plan_slot.get('distractor_spec') or {}
    planned = dspec.get('planned_misconceptions') or []

    slot = dict(plan_slot)
    slot['slot_id'] = plan_slot.get('slot_id')
    slot['doc_id'] = plan_slot.get('doc_id') or source.get('doc_id')
    slot['selected_chunk_ids'] = plan_slot.get('selected_chunk_ids') or [slot['doc_id']]
    slot['selected_context_ids'] = plan_slot.get('selected_context_ids') or source.get('selected_context_ids') or [slot['doc_id']]
    slot['context_quality'] = plan_slot.get('context_quality') or source.get('context_quality') or {}
    slot['risk_warning'] = plan_slot.get('risk_warning') or ''
    slot['topic'] = plan_slot.get('topic') or source.get('topic') or ''
    slot['cognitive_level'] = (
        plan_slot.get('cognitive_level')
        or qspec.get('cognitive_level')
        or 'Thông hiểu'
    )
    slot['difficulty_target'] = (
        plan_slot.get('difficulty_target')
        if plan_slot.get('difficulty_target') is not None
        else qspec.get('difficulty_target', 0.5)
    )
    slot['question_pattern'] = (
        plan_slot.get('question_pattern')
        or qspec.get('question_type')
        or 'conceptual'
    )
    slot['meta_pattern'] = (
        plan_slot.get('meta_pattern')
        or qspec.get('question_type')
        or 'conceptual'
    )
    slot['skill'] = plan_slot.get('skill') or qspec.get('skill_tested') or slot['topic']
    if planned:
        slot['inferred_misconceptions'] = [
            {
                'id': m.get('id', f'm_{i + 1}'),
                'wrong_form': m.get('description', ''),
                'rationale': m.get('description', ''),
            }
            for i, m in enumerate(planned)
            if isinstance(m, dict)
        ]
    slot.setdefault('inferred_misconceptions', [])
    slot.setdefault('expected_question_type', 'single_choice')
    slot.setdefault('requires_visual', False)
    return slot

def _plan_response_from_plan(plan: Dict[str, Any]) -> PlanResponse:
    slots = [
        _slot_from_plan_slot(slot)
        for slot in plan.get('slots', [])
        if isinstance(slot, dict) and slot.get('status') != 'deleted'
    ]
    return PlanResponse(
        slots=slots,
        summary=plan.get('blueprint_summary') or bp_summary(slots),
    )

def _ensure_clean_contexts(job_id: str, dataset: Dict[str, Any]) -> Dict[str, Any]:
    """Attach cached clean_contexts or build/cache them once for old jobs."""
    has_context = any(
        chunk_id != 'metadata'
        and isinstance(chunk, dict)
        and isinstance(chunk.get('clean_context'), dict)
        for chunk_id, chunk in (dataset or {}).items()
    )
    if has_context:
        return dataset

    cached = store.get_clean_contexts(job_id)
    if cached and any(k != 'metadata' for k in cached):
        attached = attach_clean_contexts(dataset, cached)
        store.save_chunks(job_id, attached)
        return attached

    meta = store.get_meta(job_id) or {}
    clean_contexts = build_clean_contexts(
        dataset,
        source_name=meta.get('source_name') or meta.get('pdf_name') or '',
    )
    attached = attach_clean_contexts(dataset, clean_contexts)
    store.save_clean_contexts(job_id, clean_contexts)
    store.save_chunks(job_id, attached)
    return attached

def run_generation(job_id: str) -> None:
    """Background entrypoint: read config + chunks, run orchestrator, save result."""
    if not cfg.has_llm_api_key():
        err = cfg.missing_llm_api_key_message()
        store.write_status(job_id, {
            'status': 'error',
            'progress': 0.0,
            'message': f'missing LLM API key: {err}',
            'error': err,
        })
        store.update_meta(job_id, status='error', error=err)
        return

    config = store.get_config(job_id)
    mode = str(config.get('mode') or cfg.DEFAULT_GENERATION_MODE or 'fast').lower()
    if mode not in {'fast', 'advanced'}:
        mode = 'fast'
    dataset = store.get_chunks(job_id)
    if not dataset:
        store.write_status(job_id, {
            'status': 'error', 'progress': 0.0,
            'message': 'chunks not parsed yet',
            'error': 'chunks.json missing',
        })
        store.update_meta(job_id, status='error', error='chunks not parsed')
        return
    dataset = _ensure_clean_contexts(job_id, dataset)

    plan = store.get_plan(job_id)
    if mode == 'advanced' and (not plan or plan.get('plan_status') != 'confirmed'):
        store.write_status(job_id, {
            'status': 'error', 'progress': 0.0,
            'message': 'plan is not confirmed',
            'error': 'plan_confirmed_required',
        })
        store.update_meta(job_id, status='error', error='plan_confirmed_required')
        return

    plan_resp = _plan_response_from_plan(plan) if mode == 'advanced' and plan else None
    num_questions = (
        len(plan_resp.slots)
        if plan_resp is not None
        else max(1, int(config.get('num_questions', 12) or 12))
    )
    use_nli = bool(config.get('use_nli', False))
    default_samples = cfg.FAST_NUM_SAMPLES_PER_SLOT if mode == 'fast' else cfg.NUM_SAMPLES_PER_SLOT
    num_samples = int(config.get('num_samples', default_samples) or default_samples)
    if mode == 'fast':
        num_samples = min(num_samples, cfg.FAST_NUM_SAMPLES_PER_SLOT)

    # Parse the Smart-Study customization config (if any) once, here.
    generation_config = cust_mod.parse(config)

    # Reset the cancel flag in case a previous run left it set.
    store.clear_cancel(job_id)
    store.update_meta(job_id, status='generating')
    store.write_status(job_id, {
        'status': 'generating', 'progress': 0.0,
        'message': f'starting {mode} generation...',
        'mode': mode,
        'llm_provider': cfg.LLM_PROVIDER,
        'cancel_requested': False,
    })

    # Each job gets its own budget window.
    reset_tracker()

    started = time.time()
    try:
        orchestrator = get_orchestrator()
        out_dir = (
            str(store.job_dir(job_id) / 'visuals')
            if config.get('include_visuals') else None
        )
        result = orchestrator.run(
            dataset=dataset,
            num_questions=num_questions,
            num_samples=num_samples,
            use_nli=use_nli,
            seed=cfg.DETERMINISTIC_SEED if hasattr(cfg, 'DETERMINISTIC_SEED') else 42,
            out_dir=out_dir,
            progress_cb=_make_progress_cb(job_id),
            difficulty_distribution=_bloom_distribution(
                str(config.get('bloom_level', 'mixed')),
                num_questions,
            ) if mode == 'fast' else None,
            plan_resp=plan_resp,
            cancel_check=lambda jid=job_id: store.is_cancel_requested(jid),
            generation_config=generation_config,
            mode=mode,
        )
    except BudgetExceeded as e:
        store.append_error(job_id, f'budget exceeded: {e}')
        store.write_status(job_id, {
            'status': 'error', 'progress': 0.0,
            'message': 'budget exceeded', 'error': str(e),
        })
        store.update_meta(job_id, status='error', error=f'budget exceeded: {e}')
        return
    except Exception as e:
        tb = traceback.format_exc()
        store.append_error(job_id, f'generation crashed: {e}\n{tb}')
        store.write_status(job_id, {
            'status': 'error', 'progress': 0.0,
            'message': 'generation crashed', 'error': str(e),
        })
        store.update_meta(job_id, status='error', error=str(e))
        return

    questions = result.get('questions', [])
    rejected = result.get('rejected', [])
    reject_summary = result.get('reject_summary') or reject_mod.summarize(rejected)
    duration_seconds = time.time() - started

    payload = {
        'metadata': {
            'job_id': job_id,
            'mode': mode,
            'llm_provider': cfg.LLM_PROVIDER,
            'generator_model': cfg.GENERATOR_MODEL,
            'judge_model': cfg.JUDGE_MODEL,
            'config': config,
            'generation_config': generation_config.to_dict(),
            'plan_id': plan.get('plan_id') if plan else None,
            'plan_status': plan.get('plan_status') if plan else 'internal_fast',
            'blueprint_summary': result.get('blueprint_summary'),
            'question_bank_summary': _question_bank_summary(questions, rejected),
            'reject_summary': reject_summary,
            'cost': result.get('cost') or get_tracker().report(),
            'attempts': result.get('attempts'),
            'duration_seconds': duration_seconds,
            'stopped_reason': result.get('stopped_reason'),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
        'questions': questions,
        'rejected': rejected,
    }
    store.save_result(job_id, payload)
    accepted_count = len(questions)
    rejected_count = len(rejected)
    stopped_reason = result.get('stopped_reason')
    cancelled = stopped_reason == 'cancelled'
    partial = bool(stopped_reason) or accepted_count < num_questions
    if cancelled:
        message = (
            f'cancelled at {accepted_count}/{num_questions}; '
            f'rejected {rejected_count}'
        )
    elif partial:
        message = (
            f'accepted {accepted_count}/{num_questions}; '
            f'rejected {rejected_count}'
        )
        if stopped_reason:
            message = f'{message}; stopped: {stopped_reason}'
    else:
        message = (
            f'accepted {accepted_count}/{num_questions}; '
            f'rejected {rejected_count}'
        )
    store.update_meta(
        job_id,
        status='cancelled' if cancelled else 'done',
        num_questions=accepted_count,
    )
    store.write_status(job_id, {
        'status': 'cancelled' if cancelled else 'done',
        'progress': 1.0,
        'message': message,
        'accepted': accepted_count,
        'target_accepted': num_questions,
        'rejected_count': rejected_count,
        'mode': mode,
        'partial': partial,
        'stopped_reason': stopped_reason,
        'cancelled': cancelled,
        'reject_summary': reject_summary,
    })
    # Always clear the cancel flag at the end, success or not.
    store.clear_cancel(job_id)
