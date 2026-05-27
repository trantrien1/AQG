"""QuestionWriter — Stage 1 của pipeline 3-stage (CoE).

Chỉ sinh stem + answer + reasoning + verifier hint. KHÔNG sinh distractor.
DistractorWriter (`pipeline/distractor.py`) chạy sau, gắn với misconception
cụ thể của câu hỏi này.

Tách concern: prompt thoáng, tập trung vào CHẤT LƯỢNG NỘI DUNG câu hỏi.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import config as cfg
from .context_utils import trim_context_for_generation
from .parsing import (
    _extract, _parse_verifier_hint, _parse_visual_block,
    _clean_source_quote, _sympy_to_natural, loads_json_maybe_repair,
)
from .llm_client import BudgetExceeded, call_llm


def parse_writer_response(text: str) -> Dict[str, Any]:
    """Parse output của QuestionWriter (chỉ stem + answer + reasoning, không distractor)."""
    raw = (text or '').strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    try:
        obj = loads_json_maybe_repair(raw)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        response = {
            'question_text': obj.get('question_text') or obj.get('Question') or '',
            'answer_explanation_text': (
                obj.get('answer_explanation_text')
                or obj.get('answer_explanation')
                or obj.get('Answer explanation')
                or ''
            ),
            'answer_text': obj.get('answer_text') or obj.get('Answer') or '',
            'source_quote_text': obj.get('source_quote_text') or obj.get('Source quote') or '',
        }
        response['source_quote_text'] = _clean_source_quote(response.get('source_quote_text', ''))
        visual = obj.get('visual')
        response['visual'] = visual if isinstance(visual, dict) else None
        hint = obj.get('verifier_hint')
        response['verifier_hint'] = hint if isinstance(hint, dict) else {'type': 'none', 'payload': {}}
        response['distractors'] = []
        response['question_text'] = _sympy_to_natural(response['question_text'])
        response['answer_explanation_text'] = _sympy_to_natural(
            response['answer_explanation_text']
        )
        response['answer_text'] = _sympy_to_natural(response['answer_text'])
        return response

    response = {
        'question_text': _extract(text, 'Question:', 'Answer explanation:'),
        'answer_explanation_text': _extract(text, 'Answer explanation:', 'Answer:'),
        'answer_text': _extract(text, 'Answer:', 'Source quote:'),
        'source_quote_text': _extract(text, 'Source quote:', 'Visual:'),
    }
    if not response['answer_text']:
        response['answer_text'] = _extract(text, 'Answer:', 'Verifier hint:')
    if not response['source_quote_text']:
        response['source_quote_text'] = _extract(text, 'Source quote:', 'Verifier hint:')
    response['source_quote_text'] = _clean_source_quote(response.get('source_quote_text', ''))

    visual_block = _extract(text, 'Visual:', 'Verifier hint:')
    response['visual'] = _parse_visual_block(visual_block) if visual_block else None

    # Verifier block kết thúc tại EOF (không có Distractors: ở stage này)
    verifier_block = _extract(text, 'Verifier hint:', None)
    response['verifier_hint'] = _parse_verifier_hint(verifier_block)

    response['distractors'] = []  # sẽ được fill bởi DistractorWriter

    # Normalize display
    response['question_text'] = _sympy_to_natural(response['question_text'])
    response['answer_explanation_text'] = _sympy_to_natural(
        response['answer_explanation_text']
    )
    response['answer_text'] = _sympy_to_natural(response['answer_text'])
    return response


def _stem_contains_embedded_options(stem: str) -> bool:
    text = re.sub(r'\s+', ' ', stem or '')
    return re.search(r'\bA[.)]\s+.+\bB[.)]\s+.+\bC[.)]\s+.+\bD[.)]\s+', text) is not None


def is_writer_valid(response: Dict[str, Any]) -> bool:
    answer = (response.get('answer_text') or '').strip().upper().rstrip('.)')
    return (
        bool(response.get('question_text'))
        and bool(response.get('answer_text'))
        and answer not in {'A', 'B', 'C', 'D'}
        and not _stem_contains_embedded_options(response.get('question_text', ''))
    )

def _conceptual_self_contained_guidance(slot: Dict[str, Any]) -> str:
    pattern = str(slot.get('question_pattern', '')).lower()
    meta_pattern = str(slot.get('meta_pattern', '')).lower()
    cognitive = str(slot.get('cognitive_level', '')).lower()
    if not (
        'concept' in pattern
        or meta_pattern == 'conceptual'
        or 'nhận biết' in cognitive
        or 'nhan biet' in cognitive
    ):
        return ''
    return (
        '\n\nYêu cầu riêng cho câu khái niệm/nhận biết:\n'
        '- Stem phải self-contained: nêu rõ tên hoặc nội dung ngắn của định lý/khái niệm, '
        'không chỉ viết "Định lý 1", "Định lý 2", "Ví dụ trên".\n'
        '- Nếu hỏi điều kiện áp dụng/không áp dụng, nhắc lại đối tượng chính trong stem '
        '(ví dụ: phương trình đặc trưng, nghiệm phức, quy tắc đếm...).\n'
        '- Distractor sau này cần cùng miền kiến thức, nên Answer cũng phải ngắn và rõ.\n'
    )


class QuestionWriter:
    """Stage 1: viết stem + answer + reasoning."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        skill_instructions: str = '',
    ):
        self.model = model_name or cfg.GENERATOR_MODEL
        skill_instructions = skill_instructions.strip()
        self.system_prompt = cfg.WRITER_SYSTEM_PROMPT
        if skill_instructions:
            self.system_prompt += f'\n\nKỸ NĂNG ÁP DỤNG:\n{skill_instructions}'

    def _build_prompt(
        self,
        slot: Dict[str, Any],
        context: str,
        feedback: Optional[List[str]] = None,
    ) -> str:
        prompt_context = trim_context_for_generation(
            context,
            slot,
            max_chars=cfg.GENERATION_CONTEXT_MAX_CHARS,
        )
        base = cfg.WRITER_USER_PROMPT.format(
            topic=slot.get('topic', ''),
            skill=slot.get('skill', ''),
            cognitive_level=slot['cognitive_level'],
            difficulty_target=slot['difficulty_target'],
            pattern=slot.get('question_pattern', 'conceptual'),
            context=prompt_context,
        )
        retry_feedback = ''
        if feedback:
            summarized = '\n'.join(f'- {item[:180]}' for item in feedback[-6:])
            retry_feedback = (
                '\n\nLỗi ở các lần thử trước cần tránh:\n'
                f'{summarized}\n'
                '- Nếu bị multi-answer/candidate_structure, hãy đổi stem để chỉ có đúng một đáp án; không hỏi kiểu quá rộng.\n'
                '- Nếu là formula selection, chỉ hỏi một đại lượng mục tiêu và đảm bảo mọi distractor sai trong chính điều kiện của stem.\n'
                '- Nếu bị verifier_error, dùng payload schema trong ví dụ hoặc type=none cho câu khái niệm không tính toán.\n'
            )
        conceptual_guidance = _conceptual_self_contained_guidance(slot)
        customization = self._customization_directive(slot)
        return (
            base
            + customization
            + conceptual_guidance
            + retry_feedback
            + '\n\nTuân thủ các skill trong system prompt. Không liệt kê A/B/C/D trong Question; '
            + 'Answer phải là nội dung đáp án, không phải chữ cái A/B/C/D.\n'
            + '\n\n'
            + cfg.WRITER_OUTPUT_FORMAT
        )

    @staticmethod
    def _customization_directive(slot: Dict[str, Any]) -> str:
        gc_dict = slot.get('_generation_config') or {}
        if not gc_dict:
            return ''
        try:
            from .customization import GenerationConfig
            gc = GenerationConfig(**{
                k: v for k, v in gc_dict.items()
                if k in GenerationConfig.__dataclass_fields__
            })
        except Exception:
            return ''
        directive = gc.writer_directive()
        if not directive:
            return ''
        return f'\n\nYêu cầu tùy chỉnh từ người dùng:\n{directive}\n'

    def write(
        self,
        slot: Dict[str, Any],
        context: str,
        num_samples: int = 2,
        feedback: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        prompt = self._build_prompt(slot, context, feedback=feedback)
        results: List[Dict[str, Any]] = []
        for i in range(num_samples):
            try:
                raw = call_llm(self.system_prompt, prompt, model=self.model)
                parsed = parse_writer_response(raw)
                if is_writer_valid(parsed):
                    parsed['_slot_id'] = slot['slot_id']
                    results.append(parsed)
            except BudgetExceeded:
                raise
            except Exception as e:
                print(f'  [writer slot {slot["slot_id"]} sample {i}] error: {e}')
                continue
        return results
