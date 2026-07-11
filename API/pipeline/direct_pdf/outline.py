"""Trích dàn ý chủ đề từ các trang PDF đã render (bước /prepare).

Chạy NỀN ngay khi người dùng chọn file — trước khi họ bấm Generate — để:
1. Gợi ý cấu hình lên form upload (chủ đề phát hiện được, chuẩn đầu ra
   đề xuất, số câu hợp lý) thay vì để người dùng đoán mò.
2. (Tương lai) làm cơ sở chia chủ đề cho sinh song song.

Dàn ý KHÔNG phụ thuộc số câu/độ khó/chuẩn đầu ra người dùng chọn nên tính
trước hoàn toàn an toàn. Mọi lỗi ở đây chỉ làm mất gợi ý, không được chặn
flow sinh câu hỏi — vì vậy `extract_outline` trả None thay vì raise.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import config as cfg
from .. import generator as gen
from ..llm_client import call_llm_with_pdf

_OUTLINE_PROMPT = (
    'Bạn được đính kèm các trang của một tài liệu học tập (thường là Toán). '
    'Hãy đọc lướt TOÀN BỘ tài liệu và trả về DUY NHẤT một JSON object đúng '
    'schema sau, không kèm markdown hay chữ nào ngoài JSON:\n'
    '{"document_title": "<tên/chủ đề chính của tài liệu, <=15 từ>",\n'
    ' "topics": ["<chủ đề hoặc dạng bài chính, <=10 từ mỗi mục>"],\n'
    ' "suggested_learning_outcomes": [{"code": "CĐR1", "description": "<chuẩn đầu ra>"}],\n'
    ' "suggested_num_questions": <số nguyên>}\n\n'
    'Yêu cầu:\n'
    '- "topics": 3-8 mục, bao phủ các phần nội dung KHÁC NHAU của tài liệu.\n'
    '- "suggested_learning_outcomes": 2-4 chuẩn đầu ra kiểu "Vận dụng được...", '
    '"Tính được...", "Giải thích được..." bám sát nội dung; đánh mã CĐR1, CĐR2... theo thứ tự.\n'
    '- "suggested_num_questions": số câu MCQ hợp lý cho lượng nội dung này (5-15).\n'
    '- Viết bằng tiếng Việt.'
)


def _clean_str(value: Any, limit: int = 200) -> str:
    return ' '.join(str(value or '').split())[:limit]


def _sanitize(obj: Any) -> Optional[Dict[str, Any]]:
    """Ép output mô hình về đúng shape; trả None nếu không có gì dùng được."""
    if not isinstance(obj, dict):
        return None
    topics: List[str] = []
    for t in (obj.get('topics') or [])[:10]:
        s = _clean_str(t, 120)
        if s and s not in topics:
            topics.append(s)

    outcomes: List[Dict[str, str]] = []
    raw_outcomes = obj.get('suggested_learning_outcomes')
    if isinstance(raw_outcomes, list):
        for i, item in enumerate(raw_outcomes[:6]):
            if isinstance(item, str):
                desc = _clean_str(item, 300)
                code = f'CĐR{len(outcomes) + 1}'
            elif isinstance(item, dict):
                desc = _clean_str(item.get('description') or item.get('text'), 300)
                code = _clean_str(item.get('code'), 20) or f'CĐR{len(outcomes) + 1}'
            else:
                continue
            if desc:
                outcomes.append({'code': code, 'description': desc})

    try:
        n = int(obj.get('suggested_num_questions'))
        suggested_n = max(1, min(30, n))
    except (TypeError, ValueError):
        suggested_n = None

    title = _clean_str(obj.get('document_title'), 160)
    if not (topics or outcomes or title):
        return None
    return {
        'document_title': title,
        'topics': topics,
        'suggested_learning_outcomes': outcomes,
        'suggested_num_questions': suggested_n,
    }


def extract_outline(
    attachment_parts: List[Dict[str, Any]],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Một call LLM vision trên các trang đã render. None nếu lỗi/không parse được."""
    if not attachment_parts:
        return None
    content = [{'type': 'text', 'text': _OUTLINE_PROMPT}] + list(attachment_parts)
    try:
        raw = call_llm_with_pdf(
            system=cfg.SYSTEM_PROMPT,
            user_content=content,
            model=model or cfg.GENERATOR_MODEL,
            max_tokens=900,
        )
    except Exception:
        return None
    return _sanitize(gen._first_json_object(raw))
