"""Customization parser — turn user UI input into a structured generation config.

The web UI exposes:
    - difficulty: "easy" | "medium" | "hard" | "applied" | "applied_high" | "mixed"
    - question_types: ["multiple_choice", "calculation", "theory", ...]
    - user_instruction: free-text Vietnamese hint (e.g. "Tập trung vào đạo hàm")
    - quick_prompts: list of pre-canned chips the user clicked

Backend turns this into a `GenerationConfig` so Planner/Writer/Distractor/
Critic can read it without parsing free text again at every stage.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


DIFFICULTY_TO_BLOOM = {
    'easy': ('Nhận biết', 0.30),
    'medium': ('Thông hiểu', 0.50),
    'hard': ('Vận dụng', 0.70),
    'applied': ('Vận dụng', 0.70),
    'applied_high': ('Vận dụng cao', 0.85),
    'mixed': ('mixed', 0.50),
}

ALLOWED_QUESTION_TYPES = (
    'multiple_choice',   # 4-option MCQ (default)
    'true_false',
    'fill_blank',
    'calculation',
    'theory',
    'example_based',
    'mixed_topics',
)


@dataclass
class GenerationConfig:
    difficulty: str = 'mixed'
    question_types: List[str] = field(default_factory=lambda: ['multiple_choice'])
    user_instruction: str = ''
    focus_topics: List[str] = field(default_factory=list)
    avoid_topics: List[str] = field(default_factory=list)
    style: str = 'default'        # "default" | "similar_to_source_material" | "exam_style"
    requires_computation: bool = False
    requires_detailed_solution: bool = True
    strict_grounding: bool = False
    quick_prompts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_default(self) -> bool:
        return (
            self.difficulty in ('mixed', '')
            and self.user_instruction.strip() == ''
            and not self.focus_topics
            and not self.avoid_topics
            and self.style in ('', 'default')
            and not self.requires_computation
            and self.question_types == ['multiple_choice']
        )

    def writer_directive(self) -> str:
        """Compact string fed into Writer prompts (Vietnamese)."""
        parts: List[str] = []
        if self.focus_topics:
            parts.append(
                'Tập trung vào các chủ đề: ' + ', '.join(self.focus_topics)
            )
        if self.avoid_topics:
            parts.append('Tránh hỏi về: ' + ', '.join(self.avoid_topics))
        if self.requires_computation:
            parts.append(
                'Yêu cầu BẮT BUỘC: câu hỏi phải đòi hỏi tính toán cụ thể '
                '(thay số, biến đổi, ra kết quả). Không hỏi lý thuyết thuần.'
            )
        if self.style == 'similar_to_source_material':
            parts.append(
                'Phong cách: giống ví dụ/đề mẫu trong tài liệu nguồn — giữ '
                'dạng bài, kỹ năng, ký hiệu tương tự nhưng KHÔNG copy nguyên văn.'
            )
        elif self.style == 'exam_style':
            parts.append('Phong cách: giống đề thi THPT, có bẫy hợp lý.')
        if self.user_instruction:
            parts.append(f'Hướng dẫn người dùng: {self.user_instruction}')
        return '\n'.join(f'- {p}' for p in parts)

    def distractor_directive(self) -> str:
        parts: List[str] = []
        if self.requires_computation:
            parts.append(
                'Distractor phải là kết quả của lỗi tính toán cụ thể '
                '(sai dấu, thay nhầm giá trị, áp dụng sai công thức, '
                'quên hằng số, nhầm điều kiện).'
            )
        if self.style == 'exam_style':
            parts.append('Distractor cần giống đề thi: hợp lý, dễ nhầm, không lộ.')
        if self.user_instruction:
            parts.append(f'Lưu ý của người dùng: {self.user_instruction}')
        return '\n'.join(f'- {p}' for p in parts)

    def critic_directive(self) -> str:
        """Fed into critic for the user_instruction_alignment trait."""
        if self.is_default():
            return ''
        bits: List[str] = []
        if self.focus_topics:
            bits.append(f'phải bám focus_topics={self.focus_topics}')
        if self.avoid_topics:
            bits.append(f'không hỏi avoid_topics={self.avoid_topics}')
        if self.requires_computation:
            bits.append('phải có tính toán cụ thể')
        if self.style == 'similar_to_source_material':
            bits.append('phong cách giống tài liệu nguồn')
        if self.user_instruction:
            bits.append(f'tuân thủ "{self.user_instruction[:120]}"')
        return '; '.join(bits)


# ==== Public parser ====

def parse(raw: Dict[str, Any] | None) -> GenerationConfig:
    """Tolerant parser — accepts whatever the UI sends.

    Recognises:
      raw["difficulty"]            — "easy"/"hard"/...
      raw["question_types"]        — list[str]
      raw["user_instruction"]      — str
      raw["quick_prompts"]         — list[str] of clicked chips
      raw["focus_topics"]          — list[str] (optional, often inferred)
      raw["avoid_topics"]          — list[str] (optional)
      raw["style"]                 — str
      raw["requires_computation"]  — bool
      raw["requires_detailed_solution"] — bool
      raw["strict_grounding"]      — bool
    """
    raw = raw or {}
    diff = (raw.get('difficulty') or 'mixed').strip().lower()
    if diff not in DIFFICULTY_TO_BLOOM:
        diff = 'mixed'

    qtypes = raw.get('question_types') or ['multiple_choice']
    if isinstance(qtypes, str):
        qtypes = [t.strip() for t in qtypes.split(',') if t.strip()]
    qtypes = [
        t.strip().lower() for t in qtypes
        if t and isinstance(t, str)
    ]
    qtypes = [t for t in qtypes if t in ALLOWED_QUESTION_TYPES] or ['multiple_choice']

    instr = (raw.get('user_instruction') or '').strip()
    quick = raw.get('quick_prompts') or []
    if isinstance(quick, str):
        quick = [quick]
    quick = [str(q).strip() for q in quick if str(q).strip()]
    if quick:
        instr = (instr + '\n' + '\n'.join(quick)).strip()

    focus = _coerce_str_list(raw.get('focus_topics'))
    avoid = _coerce_str_list(raw.get('avoid_topics'))
    style = (raw.get('style') or 'default').strip().lower()

    # Heuristic: derive focus_topics + flags from free-text instruction.
    derived_focus, derived_flags = _derive_from_instruction(instr)
    for topic in derived_focus:
        if topic not in focus:
            focus.append(topic)

    requires_computation = bool(
        raw.get('requires_computation') or 'calculation' in qtypes
        or derived_flags.get('requires_computation')
    )
    requires_detailed = raw.get('requires_detailed_solution')
    requires_detailed = True if requires_detailed is None else bool(requires_detailed)
    strict_grounding = bool(raw.get('strict_grounding') or derived_flags.get('strict_grounding'))
    if derived_flags.get('style') and style == 'default':
        style = derived_flags['style']

    return GenerationConfig(
        difficulty=diff,
        question_types=qtypes,
        user_instruction=instr,
        focus_topics=focus,
        avoid_topics=avoid,
        style=style,
        requires_computation=requires_computation,
        requires_detailed_solution=requires_detailed,
        strict_grounding=strict_grounding,
        quick_prompts=quick,
    )


def _coerce_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r'[;,]', value) if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


# ==== Heuristic free-text → flags ====

def _fold(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _derive_from_instruction(instr: str) -> tuple[list[str], dict[str, Any]]:
    """Cheap pattern match: "Tập trung vào X" → focus_topics=[X]."""
    if not instr:
        return [], {}
    flags: Dict[str, Any] = {}
    folded = _fold(instr)

    if 'tinh toan' in folded or 'tính toán' in instr.lower() or 'cau hoi can tinh' in folded:
        flags['requires_computation'] = True
    if 'giong tai lieu' in folded or 'theo tai lieu' in folded or 'giống tài liệu' in instr.lower():
        flags['style'] = 'similar_to_source_material'
    if 'de thi' in folded or 'luyen thi' in folded:
        flags['style'] = 'exam_style'
    if 'chi dung trong tai lieu' in folded or 'chỉ dùng' in instr.lower():
        flags['strict_grounding'] = True

    focus: List[str] = []
    pattern = re.compile(
        r'(?:tap\s+trung\s+vao|tập\s+trung\s+vào|chi\s+hoi\s+ve|chỉ\s+hỏi\s+về|focus\s+on)\s+([^.,;\n]+?)(?:\s+(?:và|va|hoặc|hoac|rồi|roi|sau|đồng thời|dong thoi|tạo|tao)\b|[.,;\n]|$)',
        re.IGNORECASE,
    )
    for m in pattern.finditer(instr):
        topic = m.group(1).strip()
        # Strip dangling connectors that crept into the capture.
        topic = re.sub(r'\s+(?:và|va|hoặc|hoac)\s*$', '', topic, flags=re.I).strip()
        if topic and 2 <= len(topic) <= 60:
            focus.append(topic)
    return focus, flags


# ==== Slot integration ====

def apply_to_slot(slot: Dict[str, Any], gc: GenerationConfig) -> Dict[str, Any]:
    """Attach the generation config to a slot so downstream agents see it.

    Slots are dicts; we put the config under `_generation_config` and also
    propagate `requires_computation` / `focus_topics` to fields the existing
    Planner/Writer/Distractor already understand.
    """
    out = dict(slot)
    out['_generation_config'] = gc.to_dict()
    if gc.requires_computation:
        # Force computation pattern unless already explicitly conceptual
        pattern = str(out.get('question_pattern', '')).lower()
        if 'concept' not in pattern:
            out['question_pattern'] = 'computation'
            out['meta_pattern'] = 'computation'
    if gc.focus_topics:
        out.setdefault('_focus_topics', gc.focus_topics)
    if gc.avoid_topics:
        out.setdefault('_avoid_topics', gc.avoid_topics)
    return out
