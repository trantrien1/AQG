"""Detailed explanation builder.

Produces the Smart-Study explanation block for each accepted question:

    {
      "hint": "...",
      "short_explanation": "...",
      "detailed_solution": {
        "steps": [{"title": "...", "content": "..."}, ...],
        "final_answer": "..."
      },
      "why_correct": "...",
      "why_others_wrong": [{"option": "A", "reason": "..."}, ...]
    }

V1 builds the structured output deterministically from data already produced
by Writer/Distractor:
  - answer_explanation_text → split into ordered steps
  - distractor.distractor_explanation_text → why_others_wrong[]
  - first sentence of explanation → short_explanation/why_correct
  - sympy-friendly answer → final_answer
This avoids an extra LLM round-trip for the common case while still emitting
the production schema. A future ExplanationAgent can replace this in-place.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_STEP_HEADERS = (
    'Xác định yêu cầu bài toán',
    'Áp dụng công thức / Phân tích',
    'Tính toán / Suy luận',
    'Kết luận',
)


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    s = re.sub(r'\s+', ' ', str(text)).strip()
    if not s:
        return []
    parts = re.split(r'(?<=[.!?])\s+(?=[A-ZĐÁÀẢẠÂÊÔƠƯ])', s)
    return [p.strip() for p in parts if p.strip()]


def _short(text: str, max_len: int = 220) -> str:
    s = re.sub(r'\s+', ' ', (text or '').strip())
    if len(s) <= max_len:
        return s
    cut = s.rfind('.', 0, max_len)
    if cut < max_len * 0.6:
        cut = max_len
    return s[:cut + 1].rstrip()


def _build_steps(explanation: str) -> List[Dict[str, str]]:
    """Slice the explanation into 2–4 ordered steps."""
    sentences = _split_sentences(explanation)
    if not sentences:
        return []
    if len(sentences) == 1:
        # Single sentence — present as the conclusion.
        return [{
            'title': _STEP_HEADERS[3],
            'content': sentences[0],
        }]

    # Bucket sentences into roughly equal step groups, capped at 4 steps.
    target_steps = min(4, max(2, len(sentences)))
    bucket_size = max(1, len(sentences) // target_steps)
    steps: List[Dict[str, str]] = []
    for i in range(target_steps):
        start = i * bucket_size
        end = (i + 1) * bucket_size if i < target_steps - 1 else len(sentences)
        slice_text = ' '.join(sentences[start:end]).strip()
        if not slice_text:
            continue
        title = _STEP_HEADERS[min(i, len(_STEP_HEADERS) - 1)]
        steps.append({'title': title, 'content': slice_text})
    return steps


def build(record: Dict[str, Any], candidate: Optional[Dict[str, Any]] = None,
          *, requires_detailed_solution: bool = True) -> Dict[str, Any]:
    """Return the explanation block to merge into the question record."""
    explanation = record.get('explanation_correct') or ''
    if not explanation and candidate:
        explanation = candidate.get('answer_explanation_text', '')
    short_text = _short(explanation, max_len=220)

    steps = _build_steps(explanation) if requires_detailed_solution else []
    final_answer = record.get('answer_key')
    if final_answer:
        # Translate option key → text for friendliness.
        for opt in record.get('options') or []:
            if opt.get('key') == final_answer:
                final_answer = opt.get('text') or final_answer
                break

    why_correct = (
        _short(_split_sentences(explanation)[0], max_len=200)
        if explanation else ''
    )

    answer_key = record.get('answer_key')
    why_others_wrong: List[Dict[str, str]] = []
    distractor_expl = record.get('explanation_per_distractor') or {}
    for opt in record.get('options') or []:
        key = opt.get('key')
        if key == answer_key:
            continue
        reason = distractor_expl.get(key, '')
        why_others_wrong.append({
            'option': key or '',
            'reason': _short(reason, max_len=220) or 'Không khớp với yêu cầu của câu hỏi.',
        })

    detailed = {
        'steps': steps,
        'final_answer': str(final_answer) if final_answer is not None else '',
    }

    return {
        'hint': _short(short_text, max_len=120) if short_text else '',
        'short_explanation': short_text,
        'detailed_solution': detailed,
        'why_correct': why_correct,
        'why_others_wrong': why_others_wrong,
    }
