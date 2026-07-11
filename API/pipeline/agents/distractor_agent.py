"""DistractorAgent - stage 2 misconception-grounded distractor generation."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base import BaseAgent
from .messages import DistractorRequest, DistractorResponse
from .. import config as cfg
from ..context_utils import trim_context_for_generation
from ..llm_client import BudgetExceeded, NonRetryableLLMError, call_llm
from ..parsing import loads_json_maybe_repair, normalize_display_math


class DistractorAgent(BaseAgent):
    """Generate three plausible wrong options for a writer candidate."""

    def __init__(self, use_skills: bool = True):
        super().__init__('distractor', skills=['distractor-generation'], use_skills=use_skills)
        self._skill_instructions = self.skill_instructions()

    def run(self, request: DistractorRequest) -> DistractorResponse:
        try:
            raw = call_llm(
                self._system_prompt(),
                self._user_prompt(request),
                model=cfg.GENERATOR_MODEL,
                max_tokens=1300,
            )
            distractors = _parse_distractors(raw)
            if len(distractors) != 3:
                return DistractorResponse(distractors=[], error=f'distractor_count={len(distractors)}')
            return DistractorResponse(distractors=distractors)
        except (BudgetExceeded, NonRetryableLLMError):
            raise
        except Exception as exc:
            return DistractorResponse(distractors=[], error=str(exc))

    def _system_prompt(self) -> str:
        prompt = (
            'You are DistractorAgent for Vietnamese math MCQs. '
            'Generate plausible wrong options from explicit misconceptions. '
            'Avoid multi-answer, giveaway options, and obvious nonsense.'
        )
        if self._skill_instructions:
            prompt += '\n\nSKILL INSTRUCTIONS:\n' + self._skill_instructions
        return prompt

    def _user_prompt(self, request: DistractorRequest) -> str:
        slot = request.slot
        candidate = request.candidate
        context = trim_context_for_generation(request.context, slot, max_chars=cfg.DISTRACTOR_CONTEXT_MAX_CHARS)
        feedback = '\n'.join(f'- {item}' for item in request.feedback or []) or '(none)'
        return f"""
Create exactly 3 distractors for this MCQ core.

Rules:
- Each distractor must be wrong but plausible for a learner.
- Each distractor must map to one misconception or concrete error.
- Keep answer shape consistent with the correct answer.
- Do not include the correct answer or an equivalent answer.
- Show the mistaken calculation/reason in the explanation when numeric.

Slot:
{json.dumps(slot, ensure_ascii=False)}

MCQ core:
{json.dumps({k: candidate.get(k) for k in ('question_text', 'answer_text', 'answer_explanation_text', 'why_correct')}, ensure_ascii=False)}

Feedback:
{feedback}

Source context excerpt:
{context}

Return only JSON:
{{
  "distractors": [
    {{"distractor_text":"...", "distractor_category_text":"misconception id/type", "distractor_explanation_text":"why a learner might choose it and why it is wrong"}}
  ]
}}
""".strip()


def _parse_distractors(raw: str) -> List[Dict[str, str]]:
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or '').strip())
    obj = loads_json_maybe_repair(text)
    items = obj.get('distractors') if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return []
    out: List[Dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            text_val = item.get('distractor_text') or item.get('text') or item.get('option') or ''
            category = item.get('distractor_category_text') or item.get('category') or item.get('misconception') or None
            reason = item.get('distractor_explanation_text') or item.get('reason') or item.get('explanation') or ''
        else:
            text_val = str(item or '')
            category = None
            reason = ''
        text_val = normalize_display_math(str(text_val).strip())
        reason = normalize_display_math(str(reason).strip())
        if text_val:
            out.append({
                'distractor_text': text_val,
                'distractor_category_text': category,
                'distractor_explanation_text': reason,
            })
    return out[:3]
