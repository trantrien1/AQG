"""Phản hồi người dùng -> hồ sơ sở thích (RLHF-style preference steering).

Người dùng đánh giá từng câu hỏi đã sinh (👍/👎 + tag lý do + bình luận tự do).
Module này tổng hợp các đánh giá đó thành một KHỐI CHỈ DẪN tiếng Việt
(`build_guidance`) để tiêm vào prompt của Writer/Distractor ở lượt sinh sau —
tức là học sở thích qua in-context steering thay vì huấn luyện reward model
(không cần train, hiệu lực ngay trong job).

Không có LLM nào bắt buộc: phần tổng hợp tag + ví dụ thích/chê là deterministic;
chỉ phần cô đọng bình luận tự do mới gọi LLM (best-effort, lỗi thì liệt kê thô).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Từ vựng tag — khớp với FEEDBACK_TAGS ở frontend. Tag lạ vẫn được giữ nguyên
# (liệt kê thô trong guidance) để frontend có thể mở rộng mà không sửa backend.
# ---------------------------------------------------------------------------

DISLIKE_TAG_DIRECTIVES: Dict[str, str] = {
    'too_easy': ('Nhiều câu bị chê QUÁ DỄ — tăng độ khó thực sự: thêm bước '
                 'biến đổi, không hỏi chép lại định nghĩa/công thức.'),
    'too_hard': ('Nhiều câu bị chê QUÁ KHÓ — giảm độ phức tạp, số liệu gọn '
                 'hơn, bám sát trọng tâm tài liệu.'),
    'unclear': ('Đề bị chê MƠ HỒ/KHÓ HIỂU — đề phải tự chứa, đủ dữ kiện, '
                'chỉ có một cách hiểu duy nhất.'),
    'wrong_answer': ('Người dùng NGHI SAI ĐÁP ÁN — giải lại từng bước thật '
                     'cẩn thận; đáp án phải khớp kết quả của lời giải chi tiết.'),
    'bad_distractors': ('Phương án nhiễu bị chê KÉM — mỗi distractor phải '
                        'xuất phát từ một lỗi làm bài cụ thể, không hiển '
                        'nhiên sai, không lệch dạng với đáp án.'),
    'not_relevant': ('Câu hỏi bị chê LỆCH TÀI LIỆU — chỉ hỏi khái niệm/dạng '
                     'bài thực sự xuất hiện trong tài liệu.'),
    'duplicate': ('Bị chê TRÙNG DẠNG giữa các câu — đa dạng hoá dạng bài, '
                  'ngữ cảnh, kỹ năng; không lặp lại mô-típ.'),
}

LIKE_TAG_DIRECTIVES: Dict[str, str] = {
    'good_difficulty': 'Người dùng THÍCH độ khó hiện tại — giữ mức tương tự.',
    'good_context': ('Người dùng THÍCH bài toán có ngữ cảnh thực tế — ưu tiên '
                     'đặt câu hỏi trong tình huống thực tế.'),
    'good_explanation': ('Người dùng THÍCH lời giải rõ ràng — giữ phong cách '
                         'giải chi tiết từng bước.'),
    'good_distractors': ('Người dùng THÍCH phương án nhiễu chất lượng — tiếp '
                         'tục tạo distractor từ lỗi cụ thể.'),
}

# Nhãn hiển thị (dùng khi liệt kê lý do chê theo từng câu).
TAG_LABELS: Dict[str, str] = {
    'too_easy': 'quá dễ',
    'too_hard': 'quá khó',
    'unclear': 'đề khó hiểu',
    'wrong_answer': 'nghi sai đáp án',
    'bad_distractors': 'nhiễu kém',
    'not_relevant': 'lệch tài liệu',
    'duplicate': 'trùng dạng',
    'good_difficulty': 'độ khó phù hợp',
    'good_context': 'ngữ cảnh hay',
    'good_explanation': 'giải thích rõ',
    'good_distractors': 'nhiễu chất lượng',
}

_MAX_COMMENT = 1000
_MAX_STEM_SNIPPET = 140


def normalize_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """Chuẩn hoá một entry feedback; trả None nếu thiếu question_id/rating."""
    if not isinstance(raw, dict):
        return None
    qid = str(raw.get('question_id') or '').strip()
    rating = str(raw.get('rating') or '').strip().lower()
    if not qid or rating not in ('up', 'down'):
        return None
    tags = raw.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    clean_tags: List[str] = []
    for t in tags:
        t = str(t or '').strip()
        if t and t not in clean_tags:
            clean_tags.append(t[:40])
    return {
        'question_id': qid,
        'rating': rating,
        'tags': clean_tags,
        'comment': str(raw.get('comment') or '').strip()[:_MAX_COMMENT],
        'stem': str(raw.get('stem') or '').strip(),
        'cognitive_level': str(raw.get('cognitive_level') or '').strip(),
        'created_at': str(raw.get('created_at') or ''),
    }


def normalize_feedback(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for raw in items:
        entry = normalize_entry(raw)
        if entry is not None:
            out.append(entry)
    return out


def _snippet(text: str, limit: int = _MAX_STEM_SNIPPET) -> str:
    text = ' '.join(str(text or '').split())
    return text[:limit] + ('…' if len(text) > limit else '')


def _tag_lines(items: List[Dict[str, Any]]) -> List[str]:
    """Đếm tag theo rating rồi map sang chỉ dẫn; tag lạ liệt kê thô."""
    counts: Dict[str, int] = {}
    for fb in items:
        for tag in fb.get('tags') or []:
            key = f"{fb['rating']}:{tag}"
            counts[key] = counts.get(key, 0) + 1
    lines: List[str] = []
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        rating, tag = key.split(':', 1)
        directive = (DISLIKE_TAG_DIRECTIVES if rating == 'down'
                     else LIKE_TAG_DIRECTIVES).get(tag)
        suffix = f' (x{n})' if n > 1 else ''
        if directive:
            lines.append(f'- {directive}{suffix}')
        else:
            mark = 'chê' if rating == 'down' else 'khen'
            lines.append(f'- Người dùng {mark} "{TAG_LABELS.get(tag, tag)}"{suffix}.')
    return lines


def _comment_lines(items: List[Dict[str, Any]], use_llm: bool,
                   model: Optional[str]) -> List[str]:
    """Bình luận tự do: cô đọng bằng LLM (best-effort), lỗi thì liệt kê thô."""
    commented = [fb for fb in items if fb.get('comment')]
    if not commented:
        return []
    raw_lines = [
        f"- [{'THÍCH' if fb['rating'] == 'up' else 'CHÊ'}] {fb['comment']}"
        + (f' (câu: "{_snippet(fb["stem"], 80)}")' if fb.get('stem') else '')
        for fb in commented[:12]
    ]
    if not use_llm or len(commented) < 2:
        return raw_lines
    try:
        from .llm_client import call_llm
        system = ('Bạn là trợ lý tổng hợp phản hồi. Chỉ trả về các dòng '
                  'gạch đầu dòng "- ..." tiếng Việt, không thêm gì khác.')
        user = (
            'Dưới đây là các bình luận của người dùng về những câu hỏi trắc '
            'nghiệm vừa được sinh tự động. Hãy cô đọng thành TỐI ĐA 5 chỉ dẫn '
            'hành động cho lượt sinh câu hỏi tiếp theo (mỗi chỉ dẫn một dòng '
            '"- ..."). Giữ đúng ý người dùng, không suy diễn thêm.\n\n'
            + '\n'.join(raw_lines)
        )
        raw = call_llm(system, user, model=model, temperature=0.0, max_tokens=500)
        lines = [ln.strip() for ln in str(raw or '').splitlines()
                 if ln.strip().startswith('-')]
        return lines[:5] if lines else raw_lines
    except Exception:
        return raw_lines


def build_guidance(items: Any, use_llm: bool = True,
                   model: Optional[str] = None, max_chars: int = 2500) -> str:
    """Tổng hợp feedback thành khối chỉ dẫn tiếng Việt cho prompt Writer.

    Trả chuỗi rỗng nếu không có feedback hợp lệ. Không bao giờ raise.
    """
    feedback = normalize_feedback(items)
    if not feedback:
        return ''

    sections: List[str] = []
    tag_lines = _tag_lines(feedback)
    comment_lines = _comment_lines(feedback, use_llm=use_llm, model=model)
    if tag_lines or comment_lines:
        sections.append('Yêu cầu rút ra từ phản hồi:\n'
                        + '\n'.join(tag_lines + comment_lines))

    liked = [fb for fb in feedback if fb['rating'] == 'up' and fb.get('stem')]
    if liked:
        sections.append(
            'Câu được người dùng THÍCH (dùng làm chuẩn mực về phong cách/độ khó):\n'
            + '\n'.join(f'- "{_snippet(fb["stem"])}"' for fb in liked[:5])
        )

    disliked = [fb for fb in feedback if fb['rating'] == 'down' and fb.get('stem')]
    if disliked:
        lines = []
        for fb in disliked[:8]:
            reasons = ', '.join(TAG_LABELS.get(t, t) for t in fb.get('tags') or [])
            reason_part = f' — lý do: {reasons}' if reasons else ''
            lines.append(f'- "{_snippet(fb["stem"])}"{reason_part}')
        sections.append('Câu bị CHÊ (KHÔNG tạo câu tương tự, tránh lặp lại '
                        'các lỗi nêu trên):\n' + '\n'.join(lines))

    guidance = '\n\n'.join(sections).strip()
    return guidance[:max_chars]
