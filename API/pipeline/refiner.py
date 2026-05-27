"""Refiner — Iterative critique→correction loop (MCQG-SRefine paper).

Khi CriticAgent chấm candidate dưới ngưỡng, RefinerAgent gọi LLM với feedback
rubric cụ thể để CHỈNH LẠI candidate (không sinh từ đầu). Loop tối đa N lần.

Khác với "regenerate from scratch": Refiner giữ nguyên cấu trúc tốt, chỉ
sửa chỗ critique chỉ ra (clarity, distractor plausibility, v.v.).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import config as cfg
from .parsing import _sympy_to_natural
from .llm_client import BudgetExceeded, call_llm


_REFINE_SYSTEM = (
    'Bạn là biên tập viên đề Toán. Nhận một câu hỏi MCQ + critique cụ thể, '
    'CHỈNH LẠI câu hỏi và/hoặc distractor để khắc phục các điểm bị critique. '
    'Giữ nguyên cấu trúc hợp lý; chỉ sửa chỗ cần thiết.'
)


_REFINE_USER = '''Câu hỏi MCQ hiện tại:

Question: {question}
Answer: {answer}
Distractors:
{distractors}

Critique từ rubric:
{critique}

Yêu cầu:
- Sửa các điểm bị critique chỉ ra; giữ nguyên ý chính nếu OK.
- Trả về định dạng giống y như input, không thêm chú thích.
- Công thức/biểu thức Toán hiển thị bằng LaTeX inline \\(...\\).

Format:
Question: <stem đã chỉnh>
Answer: <đáp án — có thể giữ nguyên>
Distractor 1: <text>
Distractor 2: <text>
Distractor 3: <text>'''


def _format_distractors(distractors: List[Dict[str, Any]]) -> str:
    lines = []
    for i, d in enumerate(distractors, 1):
        lines.append(f'Distractor {i}: {d.get("distractor_text", "")}')
    return '\n'.join(lines)


def _format_critique(traits: Dict[str, Dict[str, Any]]) -> str:
    """traits là output của multi-trait critic: {trait: {score, rationale}}."""
    if not traits:
        return '(không có critique chi tiết)'
    lines = []
    for trait, info in traits.items():
        if not isinstance(info, dict):
            continue
        score = info.get('score')
        rat = info.get('rationale', '')
        lines.append(f'- {trait} (score={score}): {rat}')
    return '\n'.join(lines) if lines else '(không có critique chi tiết)'


def parse_refined(text: str, original: Dict[str, Any]) -> Dict[str, Any]:
    """Parse output của refiner và merge với candidate gốc.

    Refiner chỉ trả stem + answer + 3 distractor texts. Các metadata khác
    (verifier_hint, source_quote, visual, explanation) GIỮ NGUYÊN từ candidate
    gốc — Refiner không động vào để tránh phá vỡ verifier.
    """
    refined = dict(original)  # shallow copy

    m = re.search(r'Question\s*:\s*(.+?)(?:\n\s*Answer\s*:|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        refined['question_text'] = _sympy_to_natural(m.group(1).strip())

    m = re.search(r'Answer\s*:\s*(.+?)(?:\n\s*Distractor|\Z)', text, re.DOTALL | re.IGNORECASE)
    if m:
        refined['answer_text'] = _sympy_to_natural(m.group(1).strip())

    new_distractors = []
    for i in range(1, 4):
        m = re.search(rf'Distractor\s*{i}\s*:\s*(.+?)(?:\n\s*Distractor\s*{i+1}|\Z)',
                      text, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        text_d = m.group(1).strip()
        # Giữ category/explanation từ original distractor i nếu có
        original_d = original.get('distractors', [])
        original_meta = original_d[i - 1] if i - 1 < len(original_d) else {}
        new_distractors.append({
            'distractor_category_text': original_meta.get('distractor_category_text', ''),
            'distractor_explanation_text': original_meta.get('distractor_explanation_text', ''),
            'distractor_text': _sympy_to_natural(text_d),
        })
    if len(new_distractors) == 3:
        refined['distractors'] = new_distractors

    return refined


class Refiner:
    def __init__(
        self,
        model_name: Optional[str] = None,
        skill_instructions: str = '',
    ):
        self.model = model_name or cfg.GENERATOR_MODEL
        self.system_prompt = _REFINE_SYSTEM
        skill_instructions = skill_instructions.strip()
        if skill_instructions:
            self.system_prompt += f'\n\nKỸ NĂNG ÁP DỤNG:\n{skill_instructions}'

    def refine(self, candidate: Dict[str, Any],
               critique_traits: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Gọi LLM 1 lần để refine. Trả candidate đã sửa (hoặc original nếu fail)."""
        prompt = _REFINE_USER.format(
            question=candidate.get('question_text', ''),
            answer=candidate.get('answer_text', ''),
            distractors=_format_distractors(candidate.get('distractors', [])),
            critique=_format_critique(critique_traits),
        )
        try:
            raw = call_llm(self.system_prompt, prompt, model=self.model,
                           temperature=0.5, max_tokens=900)
            return parse_refined(raw, candidate)
        except BudgetExceeded:
            raise
        except Exception as e:
            print(f'  [refiner] error: {e}')
            return candidate
