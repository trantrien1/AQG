"""Structured reject reasons (production observability).

Mỗi entry là dict thay vì string thuần để UI/CLI có thể group/filter:

    {
        "slot_id": "q_001_r02",
        "attempt": 3,
        "stage": "critic",            # writer | distractor | verifier | critic |
                                      # refiner | grounding | dedup | final | format
        "reason_code": "grounding_low",
        "score": 0.32,
        "message": "Main topic not sufficiently supported by context",
        "action": "retry_with_expanded_context",
        "candidate_id": "...",        # optional
    }

`reason_code` is the canonical machine-readable label. `message` keeps the
free-text explanation. `action` records what the orchestrator did next.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional


# ==== Canonical reason codes (the only place to extend) ====

REASON_CODES = (
    'grounding_low',
    'quote_mismatch',
    'verifier_failed',
    'multi_answer',
    'duplicate',
    'duplicate_question',
    'bad_distractors',
    'distractor_validator_failed',
    'format_error',
    'quality_low',
    'context_missing',
    'context_too_noisy',
    'generation_parse_error',
    'customization_mismatch',
    'explanation_low_quality',
    'max_attempts_exceeded',
    'budget_exceeded',
    'cancelled',
    'orchestrator_error',
    'writer_empty',
    'unknown',
)

REPAIRABLE_DISTRACTOR_CODES = {
    'bad_distractors',
    'distractor_validator_failed',
    'multi_answer',
}

REPAIRABLE_WRITER_CODES = {
    'verifier_failed',
    'duplicate_question',
    'generation_parse_error',
    'writer_empty',
    'quality_low',
    'explanation_low_quality',
}

CONTEXT_REPAIRABLE_CODES = {
    'grounding_low',
    'quote_mismatch',
    'context_missing',
    'context_too_noisy',
    'customization_mismatch',
}

TERMINAL_CODES = {
    'max_attempts_exceeded',
    'budget_exceeded',
    'cancelled',
    'orchestrator_error',
}


@dataclass
class RejectReason:
    """Single structured reject record."""
    reason_code: str = 'unknown'
    stage: str = ''
    attempt: int = 0
    message: str = ''
    score: Optional[float] = None
    action: Optional[str] = None
    slot_id: Optional[str] = None
    candidate_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d.get('extra'):
            d.pop('extra', None)
        return {k: v for k, v in d.items() if v is not None and v != ''}


def make(
    reason_code: str,
    *,
    stage: str = '',
    attempt: int = 0,
    message: str = '',
    score: Optional[float] = None,
    action: Optional[str] = None,
    slot_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Convenience constructor — returns plain dict suitable for reject_log."""
    if reason_code not in REASON_CODES:
        # Don't crash — just tag it as unknown but keep the user-supplied text.
        extra['_raw_code'] = reason_code
        reason_code = 'unknown'
    return RejectReason(
        reason_code=reason_code,
        stage=stage,
        attempt=attempt,
        message=message,
        score=score,
        action=action,
        slot_id=slot_id,
        extra=extra or {},
    ).to_dict()


# ==== Free-text → reason_code classifier ====

# Order matters — first match wins. More specific patterns first.
_HEURISTIC_PATTERNS = [
    ('cancelled', ('cancelled', 'cancel requested')),
    ('budget_exceeded', ('budget exceeded', 'budgetexceeded')),
    ('max_attempts_exceeded', ('max attempt', 'attempts exceeded', 'exhausted')),
    ('multi_answer', ('multi_answer', 'multi-answer', 'cũng được verifier xác nhận')),
    ('verifier_failed', ('verifier=false', 'verifier failed', 'verifier error')),
    ('duplicate', ('duplicate with previously accepted', 'duplicate question')),
    ('duplicate_question', ('duplicate distractor', 'source_exercise_paraphrase')),
    ('distractor_validator_failed', (
        'distractor_validator', 'option_text_sanity', 'iwf_',
        'distractor_plausibility', 'duplicate distractor', 'format_consistency',
    )),
    ('bad_distractors', ('answer_uniqueness', 'uniqueness',)),
    ('quote_mismatch', ('quote', 'unsupported_stem_numbers', 'unsupported stem')),
    ('grounding_low', ('grounding=', 'grounding ', 'grounding<', 'grounding low')),
    ('context_too_noisy', ('context_too_noisy', 'too noisy', 'high noise', 'context noise')),
    ('context_missing', ('context_missing', 'no candidate passed filters', 'no source slot', 'missing doc_id')),
    ('quality_low', ('quality=', 'final gate: quality', 'quality<', 'quality_low')),
    ('format_error', ('final formatted sanity', 'format_error', 'option_text_sanity')),
    ('customization_mismatch', ('customization', 'user_instruction_alignment', 'focus_topic')),
    ('explanation_low_quality', ('explanation_low_quality', 'detailed_solution missing')),
    ('generation_parse_error', ('writer trả 0', 'writer error', 'parse error', 'parsing failed')),
    ('orchestrator_error', ('orchestrator error', 'unexpected exception')),
]


def classify(message: str) -> str:
    """Best-effort map a free-text reject message → canonical reason_code."""
    if not message:
        return 'unknown'
    text = str(message).lower()
    for code, markers in _HEURISTIC_PATTERNS:
        for marker in markers:
            if marker in text:
                return code
    return 'unknown'


def from_message(
    message: str,
    *,
    stage: str = '',
    attempt: int = 0,
    slot_id: Optional[str] = None,
    score: Optional[float] = None,
    action: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert legacy free-text reject message → structured entry."""
    code = classify(message)
    return make(
        code,
        stage=stage,
        attempt=attempt,
        message=str(message)[:500],
        slot_id=slot_id,
        score=score,
        action=action,
    )


def coerce(entry: Any, *, default_stage: str = '', attempt: int = 0,
           slot_id: Optional[str] = None) -> Dict[str, Any]:
    """Accept either a dict (already structured) or a string (legacy)."""
    if isinstance(entry, dict) and entry.get('reason_code'):
        return entry
    if isinstance(entry, dict):
        # Dict but missing reason_code — try to classify the message.
        msg = str(entry.get('message') or entry.get('detail') or entry)
        out = from_message(
            msg, stage=entry.get('stage') or default_stage,
            attempt=int(entry.get('attempt', attempt) or attempt),
            slot_id=entry.get('slot_id') or slot_id,
            score=entry.get('score'),
            action=entry.get('action'),
        )
        return out
    return from_message(str(entry), stage=default_stage,
                       attempt=attempt, slot_id=slot_id)


def normalize_log(log: Iterable[Any], *, slot_id: Optional[str] = None,
                  default_stage: str = '') -> List[Dict[str, Any]]:
    """Normalize a mixed string/dict reject_log into structured entries."""
    out: List[Dict[str, Any]] = []
    for item in log or []:
        out.append(coerce(item, default_stage=default_stage, slot_id=slot_id))
    return out


# ==== Aggregation for status / UI ====

def summarize(rejected_records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the reject summary that GET /job/:id/status exposes.

    `rejected_records` is the formatter `reject` list (each item already has
    `reject_log` plus a top-level `reject_reason`). We reaggregate by
    reason_code so the UI can show:
        { "reason_distribution": {"grounding_low": 12, ...},
          "by_stage": {"critic": 11, "verifier": 7},
          "recent": [ ...last 8 entries... ],
          "top_failing_slots": [{slot_id, fails}] }
    """
    by_code: Counter = Counter()
    by_stage: Counter = Counter()
    by_slot: Counter = Counter()
    recent: List[Dict[str, Any]] = []
    for rec in rejected_records or []:
        slot_id = rec.get('blueprint_slot_id') or rec.get('slot_id') or ''
        log = rec.get('reject_log') or []
        for entry in log:
            ent = coerce(entry, slot_id=slot_id)
            by_code[ent.get('reason_code', 'unknown')] += 1
            stage = ent.get('stage')
            if stage:
                by_stage[stage] += 1
        # primary reason for the rejected record:
        primary_code = (
            (rec.get('reject_reason_code')
             or (log[-1].get('reason_code') if log and isinstance(log[-1], dict) else None))
            or classify(rec.get('reject_reason') or '')
        )
        if primary_code:
            by_slot[slot_id] += 1
            recent.append({
                'slot_id': slot_id,
                'reason_code': primary_code,
                'message': rec.get('reject_reason') or '',
                'attempts': rec.get('attempts') or rec.get('_attempts') or 0,
            })
    recent_tail = recent[-12:]
    suggestions = _suggestions_for(by_code)
    return {
        'reason_distribution': dict(by_code),
        'by_stage': dict(by_stage),
        'recent': recent_tail,
        'top_failing_slots': [
            {'slot_id': sid, 'fails': n}
            for sid, n in by_slot.most_common(8) if sid
        ],
        'suggestions': suggestions,
    }


def _suggestions_for(by_code: Counter) -> List[str]:
    """Translate dominant reject reasons → user-actionable hints."""
    out: List[str] = []
    if not by_code:
        return out
    top = by_code.most_common(3)
    seen = set()
    for code, _count in top:
        if code in seen:
            continue
        seen.add(code)
        if code == 'grounding_low' or code == 'quote_mismatch':
            out.append(
                'Grounding/quote nhiều lần fail — thử expand context hoặc chọn '
                'chunk khác bám sát chủ đề slot.'
            )
        elif code == 'context_missing':
            out.append('Tài liệu thiếu căn cứ cho slot — bỏ slot này hoặc đổi sang chủ đề có trong PDF.')
        elif code == 'verifier_failed':
            out.append('Verifier reject nhiều — thử tăng num_samples hoặc kiểm verifier_hint payload.')
        elif code == 'bad_distractors' or code == 'distractor_validator_failed':
            out.append('Distractor yếu — kiểm misconception list trong plan, hoặc giảm độ khó.')
        elif code in {'duplicate', 'duplicate_question'}:
            out.append('Trùng câu — giảm num_questions hoặc thêm chủ đề khác.')
        elif code == 'quality_low':
            out.append('Quality liên tục thấp — xem traits/critique và cân nhắc đổi JUDGE_MODEL mạnh hơn.')
        elif code == 'customization_mismatch':
            out.append('User instruction không khớp — chỉnh focus_topics/style hoặc giảm strict_grounding.')
    return out
