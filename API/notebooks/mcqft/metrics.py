"""Đọc đầu ra mô hình và tính chỉ số."""
from __future__ import annotations

import math
import random
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .data import jaccard, shingles

LETTERS = 'ABCD'

_RE_THINK = re.compile(r'<think>.*?</think>\s*', re.S)
_RE_HEAD = re.compile(r'^\s*#{2,4}\s*(Đề bài|Phương án|Lời giải|Đáp án)\s*:?\s*$',
                      re.M | re.I)
_RE_OPTION = re.compile(r'^\s*([A-D])\s*[.)]\s*', re.M)
_RE_FINAL = re.compile(r'Đáp\s*án(?:\s*đúng)?\s*(?:là)?\s*[:：]?\s*\**\s*\(?([A-D])\b')
_RE_CHOOSE = re.compile(r'Chọn\s*(?:đáp\s*án\s*)?\**([A-D])\b')

_KEYS = {'đề bài': 'question', 'phương án': 'choices', 'lời giải': 'solution',
         'đáp án': 'answer'}


def strip_think(text: str) -> str:
    return _RE_THINK.sub('', text).strip()


def parse_generated(text: str) -> Tuple[Dict, List[str]]:
    """Tách câu hỏi mô hình soạn. Trả về (bản ghi, danh sách lỗi định dạng)."""
    text = strip_think(text)
    parts: Dict[str, str] = {}
    heads = list(_RE_HEAD.finditer(text))
    for h, nxt in zip(heads, heads[1:] + [None]):
        key = _KEYS[h.group(1).lower()]
        end = nxt.start() if nxt else len(text)
        parts.setdefault(key, text[h.end():end].strip())
    errors: List[str] = []
    for key in ('question', 'choices', 'solution', 'answer'):
        if not parts.get(key):
            errors.append(f'missing_{key}')

    choices: List[str] = []
    marks = list(_RE_OPTION.finditer(parts.get('choices', '')))
    if [m.group(1) for m in marks] == list(LETTERS):
        body = parts['choices']
        for m, nxt in zip(marks, marks[1:] + [None]):
            choices.append(body[m.end():nxt.start() if nxt else len(body)].strip())
    elif 'choices' in parts:
        errors.append('bad_choices')
    if choices and any(not c for c in choices):
        errors.append('empty_choice')
    if len(choices) == 4 and len({re.sub(r'\s+', '', c) for c in choices}) < 4:
        errors.append('duplicate_choices')

    m = re.fullmatch(r'\**\s*([A-D])\b.*', parts.get('answer', ''), re.S)
    answer = m.group(1) if m else None
    if parts.get('answer') and answer is None:
        errors.append('bad_answer')

    record = {'question': parts.get('question', ''),
              'choices': [f'{k}. {c}' for k, c in zip(LETTERS, choices)],
              'solution': parts.get('solution', ''), 'answer': answer}
    for key in ('question', 'solution'):
        if not dollars_balanced(record[key]):
            errors.append(f'unbalanced_math_{key}')
    if any(not dollars_balanced(c) for c in choices):
        errors.append('unbalanced_math_choices')
    return record, errors


def dollars_balanced(text: str) -> bool:
    return text.replace(r'\$', '').count('$') % 2 == 0


def extract_answer(text: str) -> Optional[str]:
    """Chữ cái đáp án cuối cùng trong lời giải (``Đáp án: X`` hoặc ``Chọn X``)."""
    text = strip_think(text)
    found = _RE_FINAL.findall(text) or _RE_CHOOSE.findall(text)
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# Độ mới, độ đa dạng
# ---------------------------------------------------------------------------

def gen_text(record: Dict) -> str:
    return record['question'] + '\n' + '\n'.join(record['choices'])


class NoveltyIndex:
    """Tìm câu train giống nhất với một câu sinh ra (Jaccard 5-gram ký tự)."""

    def __init__(self, items: Sequence[Dict]):
        self.ids = [it['id'] for it in items]
        self.sets = [shingles(gen_text(it)) for it in items]
        self.index: Dict[str, List[int]] = {}
        for i, s in enumerate(self.sets):
            for g in s:
                self.index.setdefault(g, []).append(i)

    def nearest(self, record: Dict) -> Tuple[float, Optional[str]]:
        s = shingles(gen_text(record))
        hits: Dict[int, int] = {}
        for g in s:
            for i in self.index.get(g, ()):
                hits[i] = hits.get(i, 0) + 1
        best, best_id = 0.0, None
        for i, inter in hits.items():
            score = inter / (len(s) + len(self.sets[i]) - inter)
            if score > best:
                best, best_id = score, self.ids[i]
        return best, best_id


def self_similarity(records: Sequence[Dict]) -> float:
    """Jaccard trung bình giữa các cặp câu sinh ra (thấp = đa dạng)."""
    sets = [shingles(gen_text(r)) for r in records]
    total, n = 0.0, 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            total += jaccard(sets[i], sets[j])
            n += 1
    return total / n if n else 0.0


# ---------------------------------------------------------------------------
# Thống kê
# ---------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def paired_bootstrap(a: Sequence[float], b: Sequence[float], iters: int = 10000,
                     seed: int = 0) -> Dict[str, float]:
    """Khoảng tin cậy 95% của mean(b) - mean(a) trên cùng các câu."""
    assert len(a) == len(b) and a
    n = len(a)
    diffs = [y - x for x, y in zip(a, b)]
    rng = random.Random(seed)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(iters))
    return {'diff': sum(diffs) / n, 'lo': boots[int(0.025 * iters)],
            'hi': boots[int(0.975 * iters) - 1],
            'p_le_0': sum(1 for d in boots if d <= 0) / iters}


def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> Dict[str, float]:
    """Kiểm định McNemar chính xác (hai phía) cho hai hệ trên cùng tập câu."""
    only_a = sum(1 for x, y in zip(a, b) if x and not y)
    only_b = sum(1 for x, y in zip(a, b) if y and not x)
    n = only_a + only_b
    if n == 0:
        return {'only_a': 0, 'only_b': 0, 'p': 1.0}
    k = min(only_a, only_b)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {'only_a': only_a, 'only_b': only_b, 'p': min(1.0, 2 * p)}
