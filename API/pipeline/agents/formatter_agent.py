"""FormatterAgent — wrap schema. Candidate/SlotResult → record format cuối.

Cũng kéo theo `difficulty.py` (gọi từ `to_question_record`) và logic
`review_status` ('pending' | 'needs_revision').
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Dict, List, Union

from .base import BaseAgent
from .messages import (
    FormatAcceptedRequest, FormatRejectedRequest, FormatResponse,
)
from .. import config as cfg
from .. import reject as reject_mod
from ..explanation import build as build_explanation
from ..rule_validator import validate_record
from ..schema import to_question_record, reject_record


class FormatterAgent(BaseAgent):
    """Hai chế độ format:

    1. Accepted candidate → full question record (với options shuffle, KC ids,
       difficulty estimated, source quote, verification, judging, review status)
    2. Rejected slot → reject record (slot_id, topic, reject_reason, reject_log)

    Cũng quyết định `review_status`:
    - `pending_review` nếu verifier/judge ổn
    - `needs_revision` nếu verifier lỗi hoặc quality/grounding sát ngưỡng
    """

    def __init__(self):
        super().__init__('formatter', skills=['output-formatting'])

    def run(self, request: Union[FormatAcceptedRequest,
                                  FormatRejectedRequest]) -> FormatResponse:
        if isinstance(request, FormatAcceptedRequest):
            rec = to_question_record(request.slot, request.candidate, chunk=request.doc)
            rec['_attempts'] = request.attempts

            cand = request.candidate
            q = cand.get('_quality')
            g = cand.get('_grounding')
            traits = cand.get('_quality_traits') or {}
            uniq = traits.get('answer_uniqueness', {}).get('score', 1.0)
            bloom = traits.get('bloom_alignment', {}).get('score', 1.0)
            verification = cand.get('_verification') or {}
            ver_detail = (verification.get('detail') or '').lower()
            ver_errored = cand.get('_verifier_errored') or False
            ver_has_error = (
                ver_errored
                or 'error' in ver_detail
                or 'invalid literal' in ver_detail
                or 'failed' in ver_detail
            )

            # Hard cap rules: nếu vi phạm → cap quality + force needs_revision
            issues: list[str] = []
            if uniq < 0.6:
                issues.append(f'answer_uniqueness={uniq:.2f}')
            if bloom < 0.7:
                issues.append(f'bloom_alignment={bloom:.2f}')
            if ver_has_error:
                issues.append('verification.error')

            low_confidence = (
                (q is not None and q <= cfg.QUALITY_THRESHOLD + 0.05)
                or (g is not None and g <= cfg.GROUNDING_THRESHOLD + 0.05)
            )

            if issues:
                # Cap quality tối đa 0.5 + force needs_revision
                if rec.get('judging', {}).get('quality') is not None:
                    rec['judging']['quality'] = min(rec['judging']['quality'], 0.5)
                rec['review_status'] = 'needs_revision'
                rec.setdefault('review', {})['status'] = 'needs_revision'
                rec['review']['issues'] = issues
            else:
                status = 'needs_revision' if low_confidence else 'pending_review'
                rec['review_status'] = status
                rec.setdefault('review', {})['status'] = status

            # Smart-Study explanation block (deterministic v1; respects
            # `requires_detailed_solution` from the user's customization).
            gc_dict = (request.slot.get('_generation_config') or {})
            requires_detailed = bool(
                gc_dict.get('requires_detailed_solution', True)
                if gc_dict else True
            )
            try:
                explanation_block = build_explanation(
                    rec, cand,
                    requires_detailed_solution=requires_detailed,
                )
                rec['hint'] = explanation_block['hint']
                rec['short_explanation'] = explanation_block['short_explanation']
                rec['detailed_solution'] = explanation_block['detailed_solution']
                rec['why_correct'] = explanation_block['why_correct']
                rec['why_others_wrong'] = explanation_block['why_others_wrong']
                generated_solution = cand.get('detailed_solution')
                if (
                    isinstance(generated_solution, dict)
                    and isinstance(generated_solution.get('steps'), list)
                    and generated_solution.get('steps')
                ):
                    rec['detailed_solution'] = _align_generated_solution(
                        generated_solution, rec,
                    )
                if cand.get('why_correct'):
                    rec['why_correct'] = _rewrite_answer_letter_refs(
                        str(cand.get('why_correct')),
                        str(rec.get('answer_key') or ''),
                    )
                elif rec.get('why_correct'):
                    rec['why_correct'] = _rewrite_answer_letter_refs(
                        str(rec.get('why_correct')),
                        str(rec.get('answer_key') or ''),
                    )
            except Exception as exc:  # never let explanation crash the pipeline
                rec.setdefault('detailed_solution', {'steps': [], 'final_answer': ''})
                rec.setdefault('explanation_error', str(exc)[:200])

            record_issues = validate_record(rec)
            if record_issues:
                rec.setdefault('review', {})['status'] = 'needs_revision'
                rec['review_status'] = 'needs_revision'
                rec.setdefault('review', {})['issues'] = (
                    list(rec.get('review', {}).get('issues') or []) + record_issues
                )

            return FormatResponse(record=rec, is_rejected=False)

        if isinstance(request, FormatRejectedRequest):
            sr = request.slot_result
            slot_id = sr.slot_id or request.slot.get('slot_id', '')
            structured_log = reject_mod.normalize_log(sr.reject_log, slot_id=slot_id)
            primary = self._primary_reason(structured_log)
            reason_text = (
                primary.get('message')
                or primary.get('reason_code')
                or 'no candidate passed filters'
            )
            r = reject_record(request.slot, reason_text, sr.attempts)
            # Keep last 12 structured entries for UI debugging.
            r['reject_log'] = structured_log[-12:]
            r['reject_reason_code'] = primary.get('reason_code', 'unknown')
            r['reject_reason_stage'] = primary.get('stage', '')
            r['reject_reason_action'] = primary.get('action')
            return FormatResponse(record=r, is_rejected=True)

        raise TypeError(f'FormatterAgent: unsupported request type {type(request)}')

    @staticmethod
    def _primary_reason(structured_log: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pick the most actionable entry — prefer non-terminal codes over fallbacks."""
        if not structured_log:
            return {'reason_code': 'unknown'}
        # Last entry is usually the verdict; prefer it unless it's purely meta.
        meta_codes = {'orchestrator_error', 'unknown'}
        candidates = list(reversed(structured_log))
        for entry in candidates:
            code = entry.get('reason_code')
            if code and code not in meta_codes:
                return entry
        return structured_log[-1]

def _align_generated_solution(
    generated_solution: Dict[str, Any],
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep LLM-authored steps, but align answer letters after option shuffle."""
    out = copy.deepcopy(generated_solution)
    answer_key = str(record.get('answer_key') or '').strip()
    answer_text = ''
    for opt in record.get('options') or []:
        if opt.get('key') == answer_key:
            answer_text = str(opt.get('text') or '').strip()
            break
    if not answer_key:
        return out

    steps = out.get('steps') if isinstance(out.get('steps'), list) else []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        title = str(step.get('title') or '')
        content = str(step.get('content') or '')
        is_last = idx == len(steps) - 1
        if _is_conclusion_step(title, content, is_last):
            clean_answer = answer_text.rstrip(' .')
            suffix = f': {clean_answer}' if clean_answer else ''
            step['content'] = f'Chọn đáp án {answer_key}{suffix}.'
        else:
            step['content'] = _rewrite_answer_letter_refs(content, answer_key)
    if answer_text:
        out['final_answer'] = answer_text.rstrip(' .')
    return out

def _fold_ascii(text: str) -> str:
    norm = unicodedata.normalize('NFKD', text or '')
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()

def _is_conclusion_step(title: str, content: str, is_last: bool) -> bool:
    folded = _fold_ascii(f'{title} {content}')
    if 'ket luan' in folded:
        return True
    if is_last and re.search(r'\b(?:chon|dap an|phuong an|answer)\b', folded):
        return True
    return False

def _rewrite_answer_letter_refs(text: str, answer_key: str) -> str:
    if not text:
        return text
    answer_key = str(answer_key or '').strip().upper()
    if not answer_key:
        return text
    patterns = [
        (r'(?i)(chọn\s+(?:đáp\s+án|phương\s+án)\s+)[A-D]\b', rf'\g<1>{answer_key}'),
        (r'(?i)(chon\s+(?:dap\s+an|phuong\s+an)\s+)[A-D]\b', rf'\g<1>{answer_key}'),
        (r'(?i)(chọn\s+(?:đáp\s+án|phương\s+án)\s+)\\\([A-D]\\\)', rf'\g<1>{answer_key}'),
        (r'(?i)(chon\s+(?:dap\s+an|phuong\s+an)\s+)\\\([A-D]\\\)', rf'\g<1>{answer_key}'),
        (r'(?i)((?:đáp\s+án|phương\s+án)\s+đúng\s+(?:là\s+)?)[A-D]\b', rf'\g<1>{answer_key}'),
        (r'(?i)((?:dap\s+an|phuong\s+an)\s+dung\s+(?:la\s+)?)[A-D]\b', rf'\g<1>{answer_key}'),
        (r'(?i)((?:đáp\s+án|phương\s+án)\s+đúng\s+(?:là\s+)?)\\\([A-D]\\\)', rf'\g<1>{answer_key}'),
        (r'(?i)((?:dap\s+an|phuong\s+an)\s+dung\s+(?:la\s+)?)\\\([A-D]\\\)', rf'\g<1>{answer_key}'),
        (r'(?i)((?:đáp\s+án|phương\s+án)\s+)[A-D]\b', rf'\g<1>{answer_key}'),
        (r'(?i)((?:dap\s+an|phuong\s+an)\s+)[A-D]\b', rf'\g<1>{answer_key}'),
        (r'(?i)((?:đáp\s+án|phương\s+án)\s+)\\\([A-D]\\\)', rf'\g<1>{answer_key}'),
        (r'(?i)((?:dap\s+an|phuong\s+an)\s+)\\\([A-D]\\\)', rf'\g<1>{answer_key}'),
        (r'\\text\{[A-D]\}', rf'\\text{{{answer_key}}}'),
        (r'(?i)\b[A-D](?=\s+(?:\u0111\u00fang|dung)\b)', answer_key),
    ]
    out = str(text)
    out = re.sub(r'\*\*\s*([A-D])\s*\*\*', r'\1', out, flags=re.I)
    for pattern, replacement in patterns:
        out = re.sub(pattern, replacement, out)
    out = re.sub(r'(?i)\b(\u0111\u00fang|dung)\s+\1\b', r'\1', out)
    return out
