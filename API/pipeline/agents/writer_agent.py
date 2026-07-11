"""QuestionWriterAgent - stage 1 stem/answer/solution generation."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base import BaseAgent
from .messages import WriteRequest, WriteResponse
from .. import config as cfg
from ..context_utils import trim_context_for_generation
from ..llm_client import BudgetExceeded, NonRetryableLLMError, call_llm
from ..parsing import loads_json_maybe_repair, normalize_display_math


class QuestionWriterAgent(BaseAgent):
    """Generate the stem, correct answer, explanation, source quote, and verifier hint.

    Distractors are intentionally left empty; DistractorAgent owns that stage.
    """

    def __init__(self, use_skills: bool = True):
        super().__init__('question_writer', skills=['question-writing', 'bloom-taxonomy-alignment', 'verifier-hint-authoring', 'source-grounding'], use_skills=use_skills)
        self._skill_instructions = self.skill_instructions()

    def run(self, request: WriteRequest) -> WriteResponse:
        errors: List[str] = []
        candidates: List[Dict[str, Any]] = []
        samples = max(1, int(request.num_samples or 1))
        for _ in range(samples):
            try:
                raw = call_llm(
                    self._system_prompt(),
                    self._user_prompt(request),
                    model=cfg.GENERATOR_MODEL,
                    max_tokens=cfg.GEN_MAX_TOKENS,
                )
                cand = _parse_writer_response(raw)
                _validate_writer_candidate(cand)
                cand['_slot_id'] = request.slot.get('slot_id')
                cand['_writer_stage'] = True
                candidates.append(cand)
            except (BudgetExceeded, NonRetryableLLMError):
                raise
            except Exception as exc:
                errors.append(str(exc))
        return WriteResponse(
            slot_id=request.slot.get('slot_id', ''),
            candidates=candidates,
            errors=errors,
        )

    def _system_prompt(self) -> str:
        prompt = (
            'You are QuestionWriterAgent for Vietnamese math MCQs. '
            'Generate only the stem, correct answer, explanation, source quote, and verifier payload. '
            'Do not generate distractors.'
        )
        if self._skill_instructions:
            prompt += '\n\nSKILL INSTRUCTIONS:\n' + self._skill_instructions
        return prompt

    def _user_prompt(self, request: WriteRequest) -> str:
        slot = request.slot
        context = trim_context_for_generation(context=request.context, slot=slot, max_chars=cfg.GENERATION_CONTEXT_EXPANDED_MAX_CHARS)
        feedback = '\n'.join(f'- {item}' for item in request.feedback or []) or '(none)'
        return f"""
Write one new MCQ core from this slot and source context.

Hard rules:
- Preserve cognitive_level exactly: {slot.get('cognitive_level')}.
- Detailed solution minimum steps: Nhận biết >=2, Thông hiểu >=3, Vận dụng >=4, Vận dụng cao >=5.
- Do not promote or simplify Bloom level unless feedback explicitly asks.
- Do not paraphrase an existing exercise/example from context; create a new item grounded in the same concept.
- Do not generate distractors. Return distractors as an empty list.
- Student-facing math must use inline LaTeX.
- Because the output is JSON, every LaTeX backslash must be escaped: write "\\\\(x^2+1\\\\)", "\\\\frac{{a}}{{b}}", not "\\(x^2+1\\)".
- source_quote must be copied from context and support the concept/formula.
- Do not use metadata lines as source_quote (Topic, Title, Chunk type, Use note). Prefer a formula/theorem/source span line.
- If the answer is a concrete numeric result, include a correct numeric_eval verifier_payload.

Slot JSON:
{json.dumps(slot, ensure_ascii=False)}

Feedback from previous attempt:
{feedback}

Source context:
{context}

Return exactly one JSON object:
{{
  "question": "self-contained stem, no A/B/C/D labels",
  "answer": "correct answer text",
  "explanation": "brief explanation",
  "detailed_solution": {{"steps":[{{"title":"Buoc 1","content":"..."}}], "final_answer":"..."}},
  "why_correct": "why the answer is uniquely correct",
  "source_quote": "15-250 chars copied from context",
  "visual": {{"type":"none","spec":{{}},"alt_text":""}},
  "verifier_payload": {{"type":"none","payload":{{}}}},
  "distractors": []
}}
""".strip()


def _parse_writer_response(raw: str) -> Dict[str, Any]:
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or '').strip())
    obj = loads_json_maybe_repair(text)
    if not isinstance(obj, dict):
        raise ValueError('writer response is not a JSON object')
    verifier = obj.get('verifier_payload') or obj.get('verifier_hint') or {'type': 'none', 'payload': {}}
    if not isinstance(verifier, dict):
        verifier = {'type': 'none', 'payload': {}}
    verifier.setdefault('type', 'none')
    if not isinstance(verifier.get('payload'), dict):
        verifier['payload'] = {}
    detailed = obj.get('detailed_solution') if isinstance(obj.get('detailed_solution'), dict) else {}
    steps = detailed.get('steps') if isinstance(detailed.get('steps'), list) else []
    return {
        'question_text': normalize_display_math(str(obj.get('question') or obj.get('question_text') or obj.get('stem') or '').strip()),
        'answer_text': normalize_display_math(str(obj.get('answer') or obj.get('answer_text') or '').strip()),
        'answer_explanation_text': normalize_display_math(str(obj.get('explanation') or obj.get('answer_explanation_text') or '').strip()),
        'source_quote_text': str(obj.get('source_quote') or obj.get('source_quote_text') or '').strip().strip('"'),
        'visual': obj.get('visual') if isinstance(obj.get('visual'), dict) else {'type': 'none', 'spec': {}, 'alt_text': ''},
        'verifier_hint': verifier,
        'distractors': [],
        'detailed_solution': {
            'steps': [
                {
                    'title': str(step.get('title') or f'Buoc {idx + 1}'),
                    'content': normalize_display_math(str(step.get('content') or step.get('text') or '')),
                }
                for idx, step in enumerate(steps)
                if isinstance(step, dict) and str(step.get('content') or step.get('text') or '').strip()
            ],
            'final_answer': normalize_display_math(str(detailed.get('final_answer') or obj.get('answer') or '').strip()),
        },
        'why_correct': normalize_display_math(str(obj.get('why_correct') or '').strip()),
        'why_others_wrong': {},
    }


def _validate_writer_candidate(candidate: Dict[str, Any]) -> None:
    if not candidate.get('question_text'):
        raise ValueError('writer empty question_text')
    if not candidate.get('answer_text'):
        raise ValueError('writer empty answer_text')
    if not candidate.get('answer_explanation_text'):
        raise ValueError('writer empty explanation')
    if not candidate.get('source_quote_text'):
        raise ValueError('writer empty source_quote')
