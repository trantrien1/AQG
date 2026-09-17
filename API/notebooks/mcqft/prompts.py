"""Định dạng hội thoại cho hai tác vụ.

- ``gen`` (tác vụ chính): cho chủ đề, dạng bài, mức độ -> soạn một câu hỏi mới
  gồm đề, 4 phương án, lời giải, đáp án.
- ``solve`` (tác vụ phụ): cho đề và phương án -> lời giải và đáp án. Tác vụ này
  có đáp án chuẩn nên đo được độ chính xác một cách khách quan.

Đầu ra dùng các tiêu đề ``### ...`` thay vì JSON: công thức LaTeX đầy dấu ``\\``,
mà trong chuỗi JSON thì ``\\frac`` phải viết thành ``\\\\frac``; mô hình quên
một dấu là ra ``\\f`` (ký tự form feed) và cả bản ghi hỏng.
"""
from __future__ import annotations

import random
import re
from typing import Dict, List, Optional, Sequence

LETTERS = 'ABCD'

SYSTEM_GEN = (
    'Bạn là giáo viên Toán lớp 12 ở Việt Nam, soạn câu hỏi trắc nghiệm chương '
    'Nguyên hàm – Tích phân – Ứng dụng.\n'
    'Yêu cầu: đề tự chứa, không cần hình vẽ; đúng 4 phương án A, B, C, D và chỉ '
    'một phương án đúng; lời giải trình bày từng bước; mọi công thức viết bằng '
    'LaTeX đặt trong $...$.\n'
    'Trả lời đúng theo khuôn sau, không thêm gì khác:\n'
    '### Đề bài\n<đề bài>\n'
    '### Phương án\nA. <...>\nB. <...>\nC. <...>\nD. <...>\n'
    '### Lời giải\n<lời giải>\n'
    '### Đáp án\n<một chữ cái A, B, C hoặc D>'
)

SYSTEM_SOLVE = (
    'Bạn là giáo viên Toán lớp 12. Giải câu hỏi trắc nghiệm được cho, trình bày '
    'lời giải ngắn gọn từng bước, công thức viết bằng LaTeX trong $...$. '
    'Dòng cuối cùng ghi đúng dạng "Đáp án: X" với X là A, B, C hoặc D.'
)

_RE_SECTION_PREFIX = re.compile(r'^\s*DẠNG\s*\d+\s*[:.]?\s*', re.I)
_UNINFORMATIVE = {'', 'phương pháp', 'bài tập', 'ví dụ'}


def clean_section(section: Optional[str]) -> str:
    """"DẠNG 2: ÁP DỤNG TRỰC TIẾP BẢNG NGUYÊN HÀM" -> "Áp dụng trực tiếp bảng nguyên hàm"."""
    s = _RE_SECTION_PREFIX.sub('', section or '').strip(' .:')
    if s.lower() in _UNINFORMATIVE:
        return ''
    if s.isupper():
        s = s[:1] + s[1:].lower()
    return s


def gen_user(item: Dict) -> str:
    lines = [f"Chủ đề: {item['topic']}", f"Nội dung: {item['subtopic']}"]
    section = clean_section(item.get('section'))
    if section and section.lower() != item['subtopic'].lower():
        lines.append(f'Dạng bài: {section}')
    lines.append(f"Mức độ: {item['difficulty']}")
    lines.append('Hãy soạn một câu hỏi mới.')
    return '\n'.join(lines)


def strip_letter(choice: str) -> str:
    return re.sub(r'^\s*[A-D]\s*[.)]\s*', '', choice)


def gen_target(item: Dict) -> str:
    choices = '\n'.join(f'{k}. {strip_letter(c)}' for k, c in zip(LETTERS, item['choices']))
    return (f"### Đề bài\n{item['question'].strip()}\n"
            f"### Phương án\n{choices}\n"
            f"### Lời giải\n{item['solution'].strip()}\n"
            f"### Đáp án\n{item['answer']}")


def solve_user(item: Dict) -> str:
    choices = '\n'.join(f'{k}. {strip_letter(c)}' for k, c in zip(LETTERS, item['choices']))
    return f"{item['question'].strip()}\n{choices}"


def solve_target(item: Dict) -> str:
    return f"{item['solution'].strip()}\n\nĐáp án: {item['answer']}"


def gen_messages(item: Dict, shots: Sequence[Dict] = ()) -> List[Dict]:
    msgs = [{'role': 'system', 'content': SYSTEM_GEN}]
    for ex in shots:
        msgs.append({'role': 'user', 'content': gen_user(ex)})
        msgs.append({'role': 'assistant', 'content': gen_target(ex)})
    msgs.append({'role': 'user', 'content': gen_user(item)})
    return msgs


def solve_messages(item: Dict) -> List[Dict]:
    return [{'role': 'system', 'content': SYSTEM_SOLVE},
            {'role': 'user', 'content': solve_user(item)}]


def pick_shots(item: Dict, pool: Sequence[Dict], k: int, seed: int = 0) -> List[Dict]:
    """Ví dụ mẫu cho baseline few-shot: ưu tiên cùng nội dung, rồi cùng chủ đề."""
    if k <= 0:
        return []
    usable = [p for p in pool if p['id'] != item['id'] and p['solution'].strip()]
    same = [p for p in usable if p['subtopic'] == item['subtopic']]
    rest = [p for p in usable if p['topic'] == item['topic'] and p not in same]
    rng = random.Random(f"{seed}:{item['id']}")
    rng.shuffle(same)
    rng.shuffle(rest)
    return (same + rest)[:k]


# Phương án nhắc tới phương án khác thì không xáo được.
_RE_CROSS_REF = re.compile(r'\b(cả|đều|khác|trên|dưới)\b|\b[A-D]\s*(,|và|hoặc)\s*[A-D]\b', re.I)
_RE_LETTER_REF = re.compile(r'phương\s*án|đáp\s*án|\bchọn\b', re.I)


def shuffled_copy(item: Dict, rng: random.Random) -> Optional[Dict]:
    """Bản sao với thứ tự phương án bị xáo (tăng cường dữ liệu cho ``solve``).

    Bỏ qua khi phương án tham chiếu lẫn nhau hoặc lời giải nhắc tới chữ cái.
    """
    choices = [strip_letter(c) for c in item['choices']]
    if any(_RE_CROSS_REF.search(c) for c in choices) or _RE_LETTER_REF.search(item['solution']):
        return None
    order = list(range(4))
    while order == list(range(4)):
        rng.shuffle(order)
    new = dict(item)
    new['choices'] = [f'{k}. {choices[i]}' for k, i in zip(LETTERS, order)]
    new['answer'] = LETTERS[order.index(LETTERS.index(item['answer']))]
    new['id'] = item['id'] + '_shuf'
    return new


def build_examples(items: Sequence[Dict], tasks: Sequence[str], shuffle_aug: int = 0,
                   seed: int = 0) -> List[Dict]:
    """Mẫu huấn luyện: chỉ dùng câu có lời giải (câu chỉ có đáp án dạy mô hình đoán mò)."""
    rng = random.Random(seed)
    out: List[Dict] = []
    for it in items:
        if not it['solution'].strip():
            continue
        if 'gen' in tasks:
            out.append({'id': it['id'], 'task': 'gen', 'messages': gen_messages(it),
                        'target': gen_target(it)})
        if 'solve' in tasks:
            variants = [it]
            for _ in range(shuffle_aug):
                cp = shuffled_copy(it, rng)
                if cp is not None:
                    variants.append(cp)
            for v in variants:
                out.append({'id': v['id'], 'task': 'solve', 'messages': solve_messages(v),
                            'target': solve_target(v)})
    return out
