"""FastAPI app — HTTP contract for web_new frontend.

All endpoints match `web_new/src/lib/api.ts` exactly.

Run:
    python -m uvicorn web.app:app --host 127.0.0.1 --port 8080 --reload
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import (
    BackgroundTasks,
    Body,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from pipeline import config as cfg
from pipeline import customization as cust_mod
from pipeline import practice as practice_mod
from pipeline import reject as reject_mod

from . import jobs as job_runner
from . import store

app = FastAPI(title='AIED-MCQ Backend', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    ],
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'PUT', 'OPTIONS'],
    allow_headers=['*'],
)


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------

@app.get('/health')
def health() -> Dict[str, str]:
    return {'status': 'ok'}


# ----------------------------------------------------------------------
# Upload + ingestion
# ----------------------------------------------------------------------

@app.post('/upload')
async def upload(
    file: UploadFile = File(...),
    num_questions: int = Form(12),
) -> Dict[str, str]:
    """Accept a PDF, run IngestionAgent inline, return job_id.

    Ingestion is non-LLM and typically completes in seconds even for
    large PDFs. The frontend can navigate to /job/:id/chunks immediately
    after this returns.
    """
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='Chỉ chấp nhận file PDF.')

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail='File rỗng.')

    job_id = store.create_job(pdf_name=file.filename, num_questions=num_questions)
    pdf_path = store.save_pdf(job_id, content)
    # Persist initial config so /job/:id/config returns something sensible.
    store.save_config(job_id, {'num_questions': num_questions})

    result = job_runner.run_ingestion(job_id, pdf_path)
    if not result.get('ok'):
        # Job is already marked as error via run_ingestion; surface message
        # to the client so the upload page can show the real cause.
        raise HTTPException(
            status_code=422,
            detail=result.get('error') or 'Ingestion failed',
        )
    return {'job_id': job_id}


# ----------------------------------------------------------------------
# Jobs listing
# ----------------------------------------------------------------------

@app.get('/jobs')
def list_jobs() -> Dict[str, List[Dict[str, Any]]]:
    return {'jobs': store.list_jobs()}


# ----------------------------------------------------------------------
# Chunks
# ----------------------------------------------------------------------

@app.get('/job/{job_id}/chunks')
def get_chunks(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    dataset = store.get_chunks(job_id)
    if dataset is None:
        return {'chunks': {}, 'metadata': {}}
    metadata = dict(dataset.get('metadata', {}) if isinstance(dataset, dict) else {})
    contexts = store.get_clean_contexts(job_id) or {}
    ctx_meta = contexts.get('metadata') if isinstance(contexts.get('metadata'), dict) else {}
    metadata['clean_contexts_available'] = bool(contexts)
    metadata['clean_context_count'] = ctx_meta.get('num_contexts', max(0, len(contexts) - 1))
    chunks = {
        k: v for k, v in dataset.items()
        if k != 'metadata' and isinstance(v, dict) and 'context' in v
    }
    return {'chunks': chunks, 'metadata': metadata}


@app.get('/job/{job_id}/contexts')
def get_contexts(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    contexts = store.get_clean_contexts(job_id)
    if contexts is None:
        return {'contexts': {}, 'metadata': {}}
    metadata = contexts.get('metadata', {}) if isinstance(contexts, dict) else {}
    clean = {
        k: v for k, v in contexts.items()
        if k != 'metadata' and isinstance(v, dict)
    }
    return {'contexts': clean, 'metadata': metadata}


@app.post('/job/{job_id}/chunks/delete')
def delete_chunk(job_id: str, doc_id: str = Form(...)) -> Dict[str, bool]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    ok = store.delete_chunk(job_id, doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail='doc_id not found')
    # Recompute num_chunks on the meta record.
    dataset = store.get_chunks(job_id) or {}
    n_chunks = sum(
        1 for k, v in dataset.items()
        if k != 'metadata' and isinstance(v, dict) and 'context' in v
    )
    store.update_meta(job_id, num_chunks=n_chunks)
    return {'ok': True}


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in (value or '').split(',') if v.strip()]


@app.get('/job/{job_id}/config')
def get_config(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return {'config': store.get_config(job_id)}


@app.post('/job/{job_id}/configure')
def configure(
    job_id: str,
    mode: str = Form('fast'),
    num_questions: int = Form(12),
    bloom_level: str = Form('mixed'),
    include_explanation: str = Form('1'),
    include_visuals: str = Form('0'),
    question_types: str = Form(''),
    topic_filter: str = Form(''),
    # Smart-Study customization (optional; UI may send all/some/none)
    difficulty: str = Form(''),
    user_instruction: str = Form(''),
    focus_topics: str = Form(''),
    avoid_topics: str = Form(''),
    style: str = Form(''),
    requires_computation: str = Form(''),
    requires_detailed_solution: str = Form(''),
    strict_grounding: str = Form(''),
    quick_prompts: str = Form(''),
) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    config = {
        'mode': mode if mode in ('fast', 'advanced') else 'fast',
        'num_questions': num_questions,
        'bloom_level': bloom_level,
        'include_explanation': include_explanation in ('1', 'true', 'True'),
        'include_visuals': include_visuals in ('1', 'true', 'True'),
        'question_types': _split_csv(question_types),
        'topic_filter': _split_csv(topic_filter),
    }
    # Only overwrite customization keys when the request actually sent them —
    # an empty string here means "don't change".
    if difficulty:
        config['difficulty'] = difficulty.strip().lower()
    if user_instruction:
        config['user_instruction'] = user_instruction.strip()
    if focus_topics:
        config['focus_topics'] = _split_csv(focus_topics)
    if avoid_topics:
        config['avoid_topics'] = _split_csv(avoid_topics)
    if style:
        config['style'] = style.strip().lower()
    if requires_computation:
        config['requires_computation'] = requires_computation in ('1', 'true', 'True')
    if requires_detailed_solution:
        config['requires_detailed_solution'] = (
            requires_detailed_solution in ('1', 'true', 'True')
        )
    if strict_grounding:
        config['strict_grounding'] = strict_grounding in ('1', 'true', 'True')
    if quick_prompts:
        config['quick_prompts'] = _split_csv(quick_prompts)
    saved = store.save_config(job_id, config)
    store.update_meta(job_id, num_questions=num_questions)
    parsed = cust_mod.parse(saved)
    return {
        'ok': True,
        'config': saved,
        'generation_config': parsed.to_dict(),
    }


@app.post('/job/{job_id}/customize')
def customize_job(
    job_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Smart-Study customization endpoint — accepts JSON body.

    Body shape (all keys optional):
        {
          "difficulty": "easy" | "medium" | "hard" | "applied" | "applied_high" | "mixed",
          "question_types": ["multiple_choice", "calculation", ...],
          "user_instruction": "...",
          "focus_topics": ["..."],
          "avoid_topics": ["..."],
          "style": "default" | "similar_to_source_material" | "exam_style",
          "requires_computation": bool,
          "requires_detailed_solution": bool,
          "strict_grounding": bool,
          "quick_prompts": ["..."]
        }
    """
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='payload must be an object')
    saved = store.save_config(job_id, payload)
    parsed = cust_mod.parse(saved)
    return {
        'ok': True,
        'config': saved,
        'generation_config': parsed.to_dict(),
    }

# ----------------------------------------------------------------------
# Plan review
# ----------------------------------------------------------------------

def _sync_plan_slot(slot: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(slot)
    source = out.get('source_chunk') or {}
    qspec = out.get('question_spec') or {}
    dspec = out.get('distractor_spec') or {}

    if source.get('doc_id'):
        out['doc_id'] = source['doc_id']
    if source.get('topic'):
        out['topic'] = source['topic']
    if qspec.get('cognitive_level'):
        out['cognitive_level'] = qspec['cognitive_level']
    if qspec.get('difficulty_target') is not None:
        out['difficulty_target'] = qspec['difficulty_target']
    if qspec.get('question_type'):
        out['meta_pattern'] = qspec['question_type']
    if qspec.get('skill_tested'):
        out['skill'] = qspec['skill_tested']

    planned = dspec.get('planned_misconceptions') or []
    if planned:
        out['inferred_misconceptions'] = [
            {
                'id': m.get('id', f'm_{i + 1}'),
                'wrong_form': m.get('description', ''),
                'rationale': m.get('description', ''),
            }
            for i, m in enumerate(planned)
            if isinstance(m, dict)
        ]
    out.setdefault('expected_question_type', 'single_choice')
    out.setdefault('requires_visual', False)
    return out

def _normalize_plan(plan: Dict[str, Any], status: str = 'draft') -> Dict[str, Any]:
    slots = [_sync_plan_slot(s) for s in plan.get('slots', []) if isinstance(s, dict)]
    out = dict(plan)
    out['slots'] = slots
    out['total_questions'] = len(slots)
    dist: Dict[str, int] = {}
    for slot in slots:
        level = (
            slot.get('question_spec', {}).get('cognitive_level')
            or slot.get('cognitive_level')
            or 'unknown'
        )
        dist[level] = dist.get(level, 0) + 1
    out['difficulty_distribution'] = dist
    by_topic: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    misconception_counts: Dict[str, int] = {}
    misconception_labels: Dict[str, str] = {}
    for slot in slots:
        topic = (
            slot.get('source_chunk', {}).get('topic')
            or slot.get('topic')
            or 'Chưa rõ chủ đề'
        )
        qtype = (
            slot.get('question_spec', {}).get('question_type')
            or slot.get('meta_pattern')
            or slot.get('question_pattern')
            or 'conceptual'
        )
        by_topic[topic] = by_topic.get(topic, 0) + 1
        by_type[qtype] = by_type.get(qtype, 0) + 1
        for m in slot.get('distractor_spec', {}).get('planned_misconceptions', []):
            if not isinstance(m, dict):
                continue
            label = (m.get('description') or m.get('id') or '').strip()
            if not label:
                continue
            key = label.lower()
            misconception_counts[key] = misconception_counts.get(key, 0) + 1
            misconception_labels.setdefault(key, label)
    out['distribution'] = {
        'by_topic': by_topic,
        'by_difficulty': dist,
        'by_type': by_type,
    }
    if 'top_misconceptions' not in out:
        ranked = sorted(
            misconception_counts,
            key=lambda key: (-misconception_counts[key], misconception_labels[key]),
        )
        out['top_misconceptions'] = [misconception_labels[key] for key in ranked[:8]]
    out['plan_status'] = status
    out.setdefault('review_mode', 'summary')
    return out

def _public_plan(plan: Dict[str, Any], include_slots: bool = False) -> Dict[str, Any]:
    """Return the user-facing compact plan by default.

    Full slots remain persisted in `plan.json` and can be requested for debug or
    advanced editors with include_slots=true.
    """
    out = dict(plan)
    slots = out.get('slots') or []
    out['internal_slot_count'] = len(slots)
    if not include_slots:
        out.pop('slots', None)
    return out

def _difficulty_target_for_level(level: str) -> float:
    return {
        'Nhận biết': 0.30,
        'Thông hiểu': 0.50,
        'Vận dụng': 0.70,
        'Vận dụng cao': 0.85,
    }.get(level, 0.50)

def _expanded_counts(counts: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key, raw_count in (counts or {}).items():
        try:
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
        out.extend([str(key)] * count)
    return out

_SUMMARY_DISTRIBUTION_WARNING_TYPES = {
    'distribution_clone_pool',
    'distribution_total_mismatch',
}

def _append_plan_warning(plan: Dict[str, Any],
                         warning_type: str,
                         message: str,
                         slot_id: str = '') -> None:
    message = (message or '').strip()
    if not message:
        return
    details = [
        dict(item)
        for item in (plan.get('warning_details') or [])
        if isinstance(item, dict)
    ]
    detail = {'type': warning_type, 'message': message}
    if slot_id:
        detail['slot_id'] = slot_id
    if not any(
        item.get('type') == warning_type
        and item.get('message') == message
        and item.get('slot_id', '') == slot_id
        for item in details
    ):
        details.append(detail)
    plan['warning_details'] = details

    warnings = [
        str(item).strip()
        for item in (plan.get('warnings') or [])
        if str(item).strip()
    ]
    if message not in warnings:
        warnings.append(message)
    plan['warnings'] = warnings

def _prune_plan_warnings(plan: Dict[str, Any], warning_types: set[str]) -> None:
    details: List[Dict[str, Any]] = []
    removed_messages = set()
    for item in (plan.get('warning_details') or []):
        if not isinstance(item, dict):
            continue
        if item.get('type') in warning_types:
            message = (item.get('message') or '').strip()
            if message:
                removed_messages.add(message)
            continue
        details.append(dict(item))
    plan['warning_details'] = details

    warnings: List[str] = []
    for item in (plan.get('warnings') or []):
        message = str(item).strip()
        if message and message not in removed_messages and message not in warnings:
            warnings.append(message)
    for item in details:
        message = (item.get('message') or '').strip()
        if message and message not in warnings:
            warnings.append(message)
    plan['warnings'] = warnings

def _safe_count(raw_count: Any) -> int:
    try:
        return max(0, int(raw_count))
    except (TypeError, ValueError):
        return 0

def _distribution_totals(distribution: Dict[str, Any]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    if not isinstance(distribution, dict):
        return totals
    for key in ('by_topic', 'by_difficulty', 'by_type'):
        counts = distribution.get(key)
        if isinstance(counts, dict) and counts:
            totals[key] = sum(_safe_count(value) for value in counts.values())
    return totals

def _validate_distribution_totals(plan: Dict[str, Any]) -> None:
    totals = {
        key: value
        for key, value in _distribution_totals(plan.get('distribution') or {}).items()
        if value > 0
    }
    if len(set(totals.values())) <= 1:
        return
    summary = ', '.join(f'{key}={value}' for key, value in totals.items())
    _append_plan_warning(
        plan,
        'distribution_total_mismatch',
        (
            f'Distribution totals do not match ({summary}). '
            'When by_topic is present it controls the internal slot count; '
            'review the summary before confirming.'
        ),
    )

def _slot_source_key(slot: Dict[str, Any]) -> str:
    source = slot.get('source_chunk') or {}
    return str(source.get('doc_id') or slot.get('doc_id') or '').strip()

def _slot_topic(slot: Dict[str, Any]) -> str:
    return (
        slot.get('source_chunk', {}).get('topic')
        or slot.get('topic')
        or 'Chưa rõ chủ đề'
    )

def _set_slot_topic(slot: Dict[str, Any], topic: str) -> None:
    slot['topic'] = topic
    source = dict(slot.get('source_chunk') or {})
    source['topic'] = topic
    slot['source_chunk'] = source

def _apply_summary_distribution(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Apply aggregate distribution edits to internal slots.

    This keeps the simple overview table actionable without requiring users to
    edit 100 individual slots.
    """
    _prune_plan_warnings(plan, _SUMMARY_DISTRIBUTION_WARNING_TYPES)
    _validate_distribution_totals(plan)
    distribution = plan.get('distribution') or {}
    if not isinstance(distribution, dict):
        distribution = {}
    slots = [dict(s) for s in plan.get('slots', []) if isinstance(s, dict)]
    if not slots:
        plan['total_questions'] = 0
        return plan

    topic_targets = distribution.get('by_topic') or {}
    if topic_targets:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for slot in slots:
            grouped.setdefault(_slot_topic(slot), []).append(slot)

        new_slots: List[Dict[str, Any]] = []
        fallback = slots[0]
        for topic, raw_count in topic_targets.items():
            try:
                count = max(0, int(raw_count))
            except (TypeError, ValueError):
                continue
            pool = grouped.get(topic) or [
                s for old_topic, items in grouped.items()
                if topic.lower() in old_topic.lower() or old_topic.lower() in topic.lower()
                for s in items
            ]
            if not pool:
                pool = [fallback]
            unique_sources = {_slot_source_key(slot) for slot in pool}
            source_pool_size = len({key for key in unique_sources if key}) or len(pool)
            if source_pool_size and count > source_pool_size:
                _append_plan_warning(
                    plan,
                    'distribution_clone_pool',
                    (
                        f"Topic '{topic}' requested {count} questions but only "
                        f'{source_pool_size} unique source chunk(s) are available; '
                        'slots will reuse context and should be reviewed for duplicates.'
                    ),
                )
            for i in range(count):
                cloned = dict(pool[i % len(pool)])
                cloned['source_chunk'] = dict(cloned.get('source_chunk') or {})
                cloned['question_spec'] = dict(cloned.get('question_spec') or {})
                cloned['distractor_spec'] = dict(cloned.get('distractor_spec') or {})
                _set_slot_topic(cloned, str(topic))
                new_slots.append(cloned)
        if new_slots:
            slots = new_slots

    levels = _expanded_counts(distribution.get('by_difficulty') or {})
    if levels:
        for i, slot in enumerate(slots):
            level = levels[i % len(levels)]
            target = _difficulty_target_for_level(level)
            slot['cognitive_level'] = level
            slot['difficulty_target'] = target
            qspec = dict(slot.get('question_spec') or {})
            qspec['cognitive_level'] = level
            qspec['difficulty_target'] = target
            slot['question_spec'] = qspec

    qtypes = _expanded_counts(distribution.get('by_type') or {})
    if qtypes:
        for i, slot in enumerate(slots):
            qtype = qtypes[i % len(qtypes)]
            slot['meta_pattern'] = qtype
            slot['question_pattern'] = qtype
            qspec = dict(slot.get('question_spec') or {})
            qspec['question_type'] = qtype
            slot['question_spec'] = qspec

    for i, slot in enumerate(slots, start=1):
        slot['slot_id'] = f'q_{i:03d}'
    plan['slots'] = slots
    plan['total_questions'] = len(slots)
    return plan

def _set_path(obj: Dict[str, Any], path: str, value: Any) -> None:
    cur: Dict[str, Any] = obj
    parts = [p for p in path.split('.') if p]
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    if parts:
        cur[parts[-1]] = value

def _apply_plan_revision(plan: Dict[str, Any],
                         payload: Dict[str, Any]) -> Dict[str, Any]:
    next_plan = dict(plan)
    slots = list(next_plan.get('slots', []))
    edits = payload.get('edits') or []
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        action = edit.get('action')
        slot_id = edit.get('slot_id')
        idx = next((i for i, s in enumerate(slots) if s.get('slot_id') == slot_id), -1)
        if action in ('delete_slot', 'remove_slot') and idx >= 0:
            slots.pop(idx)
        elif action in ('update_slot', 'set') and idx >= 0:
            path = edit.get('path')
            if path:
                _set_path(slots[idx], path, edit.get('value'))
            for key, value in (edit.get('fields') or {}).items():
                _set_path(slots[idx], key, value)
        elif action == 'add_slot':
            new_slot = dict(edit.get('slot') or {})
            if new_slot:
                new_slot.setdefault('slot_id', f'q_{len(slots) + 1:03d}')
                slots.append(new_slot)

    instruction = (payload.get('instruction') or payload.get('text') or '').strip()
    if instruction:
        history = list(next_plan.get('revision_history') or [])
        history.append({
            'instruction': instruction,
            'note': 'Natural-language revision recorded. Submit structured edits or a full plan to apply exact changes.',
        })
        next_plan['revision_history'] = history
    if isinstance(payload.get('distribution'), dict):
        next_plan['distribution'] = payload['distribution']
    next_plan['slots'] = slots
    next_plan = _apply_summary_distribution(next_plan)
    return _normalize_plan(next_plan, status='draft')

@app.post('/job/{job_id}/plan/generate')
def generate_plan(
    job_id: str,
    num_questions: int = Form(12),
    bloom_level: str = Form('mixed'),
    include_slots: bool = False,
) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    dataset = store.get_chunks(job_id)
    if dataset is None:
        raise HTTPException(status_code=409, detail='Chunks not ready.')

    store.save_config(job_id, {
        'num_questions': num_questions,
        'bloom_level': bloom_level,
    })
    distribution = job_runner._bloom_distribution(bloom_level, num_questions)
    meta = store.get_meta(job_id) or {}
    plan = job_runner.get_orchestrator().planner.build_rich_plan(
        dataset=dataset,
        num_questions=num_questions,
        seed=cfg.DETERMINISTIC_SEED,
        difficulty_distribution=distribution,
        source=meta.get('source_name') or meta.get('pdf_name') or '',
    )
    store.clear_result(job_id)
    saved = store.save_plan(job_id, _normalize_plan(plan, status='draft'), status='draft')
    store.update_meta(job_id, status='plan_draft', plan_id=saved.get('plan_id'))
    store.write_status(job_id, {
        'status': 'plan_draft',
        'progress': 0.20,
        'message': f'plan draft ready: {len(saved.get("slots", []))} slot(s)',
    })
    return {'ok': True, 'plan': _public_plan(saved, include_slots=include_slots)}

@app.get('/job/{job_id}/plan')
def get_plan(job_id: str, include_slots: bool = False) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    plan = store.get_plan(job_id)
    if plan is None:
        raise HTTPException(status_code=404, detail='Plan not generated')
    return {'plan': _public_plan(plan, include_slots=include_slots)}

@app.put('/job/{job_id}/plan')
def put_plan(
    job_id: str,
    plan: Dict[str, Any] = Body(...),
    include_slots: bool = False,
) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    if 'slots' not in plan:
        existing = store.get_plan(job_id) or {}
        plan = {**existing, **plan, 'slots': existing.get('slots', [])}
    plan = _apply_summary_distribution(plan)
    store.clear_result(job_id)
    saved = store.save_plan(job_id, _normalize_plan(plan, status='draft'), status='draft')
    store.update_meta(job_id, status='plan_draft', plan_id=saved.get('plan_id'))
    return {'ok': True, 'plan': _public_plan(saved, include_slots=include_slots)}

@app.post('/job/{job_id}/plan/revise')
def revise_plan(
    job_id: str,
    payload: Dict[str, Any] = Body(...),
    include_slots: bool = False,
) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    plan = store.get_plan(job_id)
    if plan is None:
        raise HTTPException(status_code=404, detail='Plan not generated')
    has_structured_change = bool(payload.get('edits')) or isinstance(payload.get('distribution'), dict)
    has_instruction = bool((payload.get('instruction') or payload.get('text') or '').strip())
    revised = _apply_plan_revision(plan, payload)
    store.clear_result(job_id)
    saved = store.save_plan(job_id, revised, status='draft')
    store.update_meta(job_id, status='plan_draft', plan_id=saved.get('plan_id'))
    response: Dict[str, Any] = {
        'ok': True,
        'applied': has_structured_change,
        'plan': _public_plan(saved, include_slots=include_slots),
    }
    if has_instruction and not has_structured_change:
        response['hint'] = (
            'Natural-language revision is recorded only. Submit structured '
            'distribution or edits to apply changes without adding a new agent.'
        )
    return response

@app.post('/job/{job_id}/plan/confirm')
def confirm_plan(job_id: str, include_slots: bool = False) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    plan = store.confirm_plan(job_id)
    if plan is None:
        raise HTTPException(status_code=404, detail='Plan not generated')
    if not plan.get('slots'):
        raise HTTPException(status_code=409, detail='Plan has no slots')
    store.update_meta(job_id, status='plan_confirmed', plan_id=plan.get('plan_id'))
    store.write_status(job_id, {
        'status': 'plan_confirmed',
        'progress': 0.25,
        'message': 'plan confirmed; generation unlocked',
    })
    return {'ok': True, 'plan': _public_plan(plan, include_slots=include_slots)}

# ----------------------------------------------------------------------
# Generate (background) + status polling
# ----------------------------------------------------------------------

@app.post('/job/{job_id}/generate')
def start_generate(
    job_id: str,
    background_tasks: BackgroundTasks,
    mode: str = Form('fast'),
    num_questions: int = Form(12),
    num_samples: int = Form(cfg.NUM_SAMPLES_PER_SLOT),
    use_nli: str = Form('0'),
    bloom_level: str = Form('mixed'),
) -> Dict[str, bool]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    if store.get_chunks(job_id) is None:
        raise HTTPException(
            status_code=409,
            detail='Chunks not ready. Wait for ingestion to finish.',
        )
    mode = mode if mode in ('fast', 'advanced') else 'fast'
    plan = store.get_plan(job_id)
    if mode == 'advanced' and (not plan or plan.get('plan_status') != 'confirmed'):
        raise HTTPException(
            status_code=409,
            detail='Plan must be generated and confirmed before generation.',
        )

    # Prevent concurrent generation for the same job
    current_status = store.get_status(job_id)
    if current_status.get('status') in ('generating', 'running'):
        raise HTTPException(
            status_code=409,
            detail='Generation already in progress for this job.',
        )

    # Persist the runtime overrides into config.json so a refresh of the
    # generate page picks up the same parameters and run_generation reads
    # a single source of truth.
    store.save_config(job_id, {
        'mode': mode,
        'num_questions': num_questions,
        'num_samples': num_samples,
        'use_nli': use_nli in ('1', 'true', 'True'),
        'bloom_level': bloom_level,
    })

    background_tasks.add_task(job_runner.run_generation, job_id)
    return {'ok': True}


@app.get('/job/{job_id}/status')
def get_status(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    status = store.get_status(job_id) or {}
    # If status doesn't already include a reject_summary (older runs), build it
    # on the fly from result.json so the UI always has something to render.
    if 'reject_summary' not in status:
        result = store.get_result(job_id)
        if result and result.get('rejected'):
            status['reject_summary'] = reject_mod.summarize(result.get('rejected'))
    status['cancel_requested'] = store.is_cancel_requested(job_id)
    return status


@app.post('/job/{job_id}/cancel')
def cancel_job(job_id: str) -> Dict[str, Any]:
    """Mark this job for cancellation.

    The orchestrator polls a cancel-flag between slots/attempts and stops
    promptly while persisting any partial accepted questions.
    """
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current = store.get_status(job_id) or {}
    if current.get('status') in ('done', 'cancelled', 'error'):
        return {
            'ok': False,
            'reason': 'already_finished',
            'status': current.get('status'),
        }
    ok = store.request_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=500, detail='failed to request cancel')
    # Reflect intent immediately so the UI button can flip state without waiting
    # for the next progress callback.
    current['cancel_requested'] = True
    current['message'] = 'cancel requested — stopping after current step'
    store.write_status(job_id, current)
    return {'ok': True}


@app.get('/job/{job_id}/rejects')
def get_rejects(job_id: str) -> Dict[str, Any]:
    """Detailed reject summary + recent reject samples for the UI."""
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    result = store.get_result(job_id) or {}
    rejected = result.get('rejected') or []
    summary = reject_mod.summarize(rejected)
    return {
        'summary': summary,
        'rejects': [
            {
                'question_id': r.get('question_id'),
                'slot_id': r.get('blueprint_slot_id'),
                'topic': r.get('topic'),
                'reject_reason': r.get('reject_reason'),
                'reject_reason_code': r.get('reject_reason_code'),
                'reject_reason_stage': r.get('reject_reason_stage'),
                'reject_log': r.get('reject_log') or [],
                'attempts': r.get('attempts'),
            }
            for r in rejected
        ],
    }


# ----------------------------------------------------------------------
# Questions + review + export
# ----------------------------------------------------------------------

@app.get('/job/{job_id}/questions')
def get_questions(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    result = store.get_result(job_id)
    if result is None:
        # Generation hasn't run yet.
        return {'questions': [], 'rejected': []}
    return {
        'questions': result.get('questions', []),
        'rejected': result.get('rejected', []),
    }


@app.post('/job/{job_id}/review')
def review_question(
    job_id: str,
    question_id: str = Form(...),
    action: str = Form(...),
) -> Dict[str, bool]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    if action not in ('approve', 'reject'):
        raise HTTPException(status_code=400, detail='action must be approve|reject')
    target = 'approved' if action == 'approve' else 'rejected'
    ok = store.update_question_review(job_id, question_id, target)
    if not ok:
        raise HTTPException(status_code=404, detail='question_id not found')
    return {'ok': True}


@app.get('/job/{job_id}/export')
def export(job_id: str) -> Any:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='No result to export yet')
    path = store.export_path(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail='No result to export yet')
    return FileResponse(
        path=str(path),
        filename=f'{job_id}.json',
        media_type='application/json',
    )


# ----------------------------------------------------------------------
# Smart Practice mode
# ----------------------------------------------------------------------

def _accepted_questions(job_id: str) -> List[Dict[str, Any]]:
    result = store.get_result(job_id) or {}
    return [
        q for q in result.get('questions', [])
        if q.get('answer_key')
    ]


@app.post('/job/{job_id}/practice/start')
def practice_start(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    questions = _accepted_questions(job_id)
    if not questions:
        raise HTTPException(
            status_code=409,
            detail='No accepted questions to practice; generate first.',
        )
    try:
        session = practice_mod.start_session(store.job_dir(job_id), questions)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    qid = session.get('current_question_id')
    current = next(
        (q for q in questions if q.get('question_id') == qid), None,
    )
    return {
        'session': session,
        'question': practice_mod.public_question(current) if current else None,
    }


@app.get('/job/{job_id}/practice/{session_id}')
def practice_get(job_id: str, session_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    session = practice_mod.get_session(store.job_dir(job_id), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    questions = _accepted_questions(job_id)
    qid = session.get('current_question_id')
    current = next(
        (q for q in questions if q.get('question_id') == qid), None,
    )
    return {
        'session': session,
        'question': practice_mod.public_question(current) if current else None,
    }


@app.get('/job/{job_id}/practice')
def practice_list(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return {'sessions': practice_mod.list_sessions(store.job_dir(job_id))}


@app.post('/job/{job_id}/practice/{session_id}/answer')
def practice_answer(
    job_id: str, session_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    qid = payload.get('question_id')
    answer_key = payload.get('answer_key')
    if not qid or not answer_key:
        raise HTTPException(status_code=400,
                            detail='question_id and answer_key required')
    questions = _accepted_questions(job_id)
    try:
        verdict = practice_mod.submit_answer(
            store.job_dir(job_id), session_id,
            qid, str(answer_key), questions,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return verdict


@app.post('/job/{job_id}/practice/{session_id}/feedback')
def practice_feedback(
    job_id: str, session_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    qid = payload.get('question_id')
    feedback = payload.get('feedback')
    if not qid or feedback not in ('like', 'dislike'):
        raise HTTPException(
            status_code=400,
            detail="payload requires question_id + feedback in {'like','dislike'}",
        )
    try:
        return practice_mod.submit_feedback(
            store.job_dir(job_id), session_id, qid, feedback,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post('/job/{job_id}/practice/{session_id}/next')
def practice_next(job_id: str, session_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    questions = _accepted_questions(job_id)
    try:
        nxt = practice_mod.next_question(
            store.job_dir(job_id), session_id, questions,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        'question': practice_mod.public_question(nxt) if nxt else None,
        'finished': nxt is None,
    }


# ----------------------------------------------------------------------
# Benchmark (read-only metrics)
# ----------------------------------------------------------------------

@app.get('/job/{job_id}/benchmark')
def benchmark_endpoint(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    from pipeline import benchmark as bench_mod
    metrics = bench_mod.benchmark_job(job_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail='No result.json yet')
    return {'metrics': metrics}


# ----------------------------------------------------------------------
# Error handler — turn unexpected exceptions into JSON
# ----------------------------------------------------------------------

@app.exception_handler(Exception)
def unhandled_exception(_request, exc: Exception):  # noqa: ANN001
    return JSONResponse(
        status_code=500,
        content={'detail': f'{type(exc).__name__}: {exc}'},
    )
