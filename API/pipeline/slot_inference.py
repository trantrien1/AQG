"""LLM-driven inference of pattern + skill + misconceptions per chunk.

Pivot per user feedback: KHÔNG hardcode `QUESTION_PATTERNS` với keyword matching.
LLM tự đọc context và đề xuất:
  - meta_pattern : computation | conceptual | reasoning | application
  - pattern_id   : free-text snake_case mô tả dạng cụ thể
  - skill        : kỹ năng test
  - misconceptions: list lỗi cụ thể với nội dung chunk

Inference cache theo chunk (`doc_id`) — nhiều slot từ cùng chunk chia sẻ kết quả.
Khi không có API key hoặc LLM lỗi → trả về structure rỗng để caller fallback.
"""
from __future__ import annotations

import json
import re
from threading import Lock
from typing import Any, Dict, Optional

from . import config as cfg
from .llm_client import BudgetExceeded, call_llm


_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = Lock()


_SYSTEM = (
    'Bạn là chuyên gia thiết kế đề Toán. Đọc ngữ cảnh và đề xuất dạng câu hỏi '
    'phù hợp NHẤT với nội dung — không bị giới hạn bởi bất kỳ danh sách có sẵn.'
)


_USER = '''\
Đọc đoạn Toán dưới đây và đề xuất:
1. meta_pattern: một trong [computation, conceptual, reasoning, application]
2. pattern_id: snake_case mô tả dạng câu hỏi cụ thể nhất (tự đặt — KHÔNG bị giới hạn)
3. skill: kỹ năng cụ thể câu hỏi kiểm tra (vài từ tiếng Việt)
4. misconceptions: 4–6 lỗi học sinh thường mắc khi làm bài thuộc nội dung này;
   mỗi lỗi gồm id snake_case, wrong_form (mô tả lỗi ngắn), rationale (vì sao sai).

Ngữ cảnh (chủ đề: {topic}):
{context}

Trả về JSON một dòng đúng schema:
{{"meta_pattern":"...","pattern_id":"...","skill":"...","misconceptions":[{{"id":"...","wrong_form":"...","rationale":"..."}}]}}

Không bọc markdown, không thêm chú thích.'''


def _parse(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    try:
        obj = json.loads(raw)
    except Exception:
        # Cố gắng tìm khối JSON trong response
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    obj.setdefault('meta_pattern', 'conceptual')
    obj.setdefault('pattern_id', '')
    obj.setdefault('skill', '')
    obj.setdefault('misconceptions', [])
    if not isinstance(obj['misconceptions'], list):
        obj['misconceptions'] = []
    return obj


def infer_for_chunk(
    doc_id: str,
    topic: str,
    context: str,
    skill_instructions: str = '',
) -> Dict[str, Any]:
    """Return {meta_pattern, pattern_id, skill, misconceptions}.

    Cached theo doc_id — mỗi chunk chỉ tốn 1 LLM call dù sinh nhiều slot từ
    chunk đó. Lỗi LLM/budget → trả structure rỗng (caller fallback).
    """
    skill_instructions = (skill_instructions or '').strip()
    key = doc_id or topic
    if skill_instructions:
        key = f'{key}:{hash(skill_instructions) & 0xffff}'
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached

    if not cfg.has_llm_api_key():
        empty: Dict[str, Any] = {
            'meta_pattern': '', 'pattern_id': '', 'skill': '', 'misconceptions': [],
        }
        with _CACHE_LOCK:
            _CACHE[key] = empty
        return empty

    user = _USER.format(topic=topic or '(không rõ)', context=(context or '')[:3500])
    parsed: Optional[Dict[str, Any]] = None
    try:
        system = _SYSTEM
        if skill_instructions:
            system += f'\n\nKỸ NĂNG ÁP DỤNG:\n{skill_instructions}'
        raw = call_llm(system, user, model=cfg.JUDGE_MODEL,
                       temperature=0.2, max_tokens=700)
        parsed = _parse(raw)
    except BudgetExceeded:
        raise
    except Exception:
        parsed = None

    result = parsed or {
        'meta_pattern': '', 'pattern_id': '', 'skill': '', 'misconceptions': [],
    }
    with _CACHE_LOCK:
        _CACHE[key] = result
    return result


def reset_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
