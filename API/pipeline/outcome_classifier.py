"""Phân loại câu hỏi theo Chuẩn đầu ra (CĐR / learning outcome) do người dùng nhập.

Chạy SAU khi sinh xong toàn bộ câu hỏi: một lượt gọi LLM text-only nhận danh
sách CĐR + danh sách câu hỏi, trả mapping question_id -> [mã CĐR]. Best-effort:
mọi lỗi (LLM, parse) chỉ làm mất nhãn phân loại, KHÔNG làm hỏng job sinh câu.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import config as cfg
from .llm_client import call_llm

_SYSTEM = (
    'Bạn là chuyên gia đo lường và đánh giá trong giáo dục. Nhiệm vụ: gán mỗi '
    'câu hỏi trắc nghiệm vào (các) chuẩn đầu ra phù hợp nhất dựa trên nội dung '
    'và kỹ năng mà câu hỏi kiểm tra. Chỉ trả về JSON hợp lệ, không kèm văn bản khác.'
)


def normalize_outcomes(raw: Any) -> List[Dict[str, str]]:
    """Chuẩn hoá input CĐR của người dùng thành [{'code','description'}].

    Chấp nhận: list[str] (mỗi phần tử một mô tả; nếu bắt đầu bằng "MÃ: mô tả"
    thì tách mã), list[dict] có code/description, hoặc chuỗi nhiều dòng.
    Mã thiếu được cấp tự động CĐR1, CĐR2...
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        items: List[Any] = [line for line in raw.splitlines()]
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    out: List[Dict[str, str]] = []
    seen_codes = set()
    for item in items:
        code = ''
        desc = ''
        if isinstance(item, dict):
            code = str(item.get('code') or item.get('id') or '').strip()
            desc = str(item.get('description') or item.get('text') or '').strip()
        else:
            text = str(item or '').strip()
            if not text:
                continue
            # "CLO1: mô tả" / "CĐR 2 - mô tả" -> tách mã đứng đầu.
            m = re.match(r'^([A-Za-zĐđ][\w.ĐđƯưÂâ]{0,15}?\s?\d{0,3})\s*[:\-–]\s+(.+)$', text)
            if m and len(m.group(1).strip()) <= 12:
                code = m.group(1).strip().replace(' ', '')
                desc = m.group(2).strip()
            else:
                desc = text
        if not desc:
            continue
        if not code:
            code = f'CĐR{len(out) + 1}'
        base = code
        n = 2
        while code in seen_codes:
            code = f'{base}.{n}'
            n += 1
        seen_codes.add(code)
        out.append({'code': code, 'description': desc[:500]})
    return out


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not isinstance(text, str):
        return None
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.M).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if 0 <= start < end:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def parse_assignments(raw: str, valid_codes: List[str],
                      valid_ids: List[str]) -> Dict[str, List[str]]:
    """Parse phản hồi LLM -> {question_id: [codes]}; lọc mã/id không hợp lệ."""
    obj = _extract_json(raw)
    if not obj:
        return {}
    items = obj.get('assignments')
    if not isinstance(items, list):
        return {}
    codes = set(valid_codes)
    ids = set(valid_ids)
    out: Dict[str, List[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        qid = str(item.get('question_id') or '').strip()
        if qid not in ids:
            continue
        raw_codes = item.get('outcomes')
        if not isinstance(raw_codes, list):
            continue
        kept = [str(c).strip() for c in raw_codes if str(c).strip() in codes]
        # unique, giữ thứ tự
        out[qid] = list(dict.fromkeys(kept))
    return out


def _user_prompt(outcomes: List[Dict[str, str]],
                 questions: List[Dict[str, Any]]) -> str:
    outcome_lines = '\n'.join(
        f"- {o['code']}: {o['description']}" for o in outcomes)
    q_blocks = []
    for q in questions:
        stem = ' '.join(str(q.get('stem') or '').split())[:600]
        answer = ''
        for opt in q.get('options') or []:
            if opt.get('key') == q.get('answer_key'):
                answer = str(opt.get('text') or '')[:120]
                break
        q_blocks.append(
            f"question_id: {q.get('question_id')}\n"
            f"  đề: {stem}\n"
            f"  đáp án: {answer}"
        )
    body = '\n'.join(q_blocks)
    return f"""
Các chuẩn đầu ra (CĐR) của học phần:
{outcome_lines}

Danh sách câu hỏi trắc nghiệm:
{body}

Với MỖI câu hỏi, chọn (các) mã CĐR mà câu hỏi đó kiểm tra trực tiếp — thường là
1 mã, tối đa 2 mã khi câu hỏi thật sự bao phủ cả hai. Nếu không CĐR nào phù hợp,
trả mảng rỗng []. KHÔNG bịa mã mới ngoài danh sách trên.

Chỉ trả về JSON đúng schema:
{{"assignments": [{{"question_id": "...", "outcomes": ["<mã CĐR>"]}}]}}
""".strip()


def classify_questions(
    questions: List[Dict[str, Any]],
    outcomes: List[Dict[str, str]],
    model: Optional[str] = None,
    batch_size: int = 20,
) -> Dict[str, List[str]]:
    """Gán CĐR cho từng câu hỏi. Trả {question_id: [codes]}; lỗi -> {} (best-effort)."""
    outcomes = [o for o in (outcomes or [])
                if isinstance(o, dict) and o.get('code') and o.get('description')]
    questions = [q for q in (questions or []) if q.get('question_id')]
    if not outcomes or not questions:
        return {}

    valid_codes = [o['code'] for o in outcomes]
    result: Dict[str, List[str]] = {}
    for i in range(0, len(questions), batch_size):
        batch = questions[i:i + batch_size]
        try:
            raw = call_llm(
                _SYSTEM,
                _user_prompt(outcomes, batch),
                # Phân loại CĐR là việc chấm nhẹ (temperature 0) — dùng
                # JUDGE_MODEL (mặc định = generator model khi không set env).
                model=model or cfg.JUDGE_MODEL,
                temperature=0.0,
                max_tokens=max(800, 90 * len(batch)),
            )
        except Exception:
            continue
        result.update(parse_assignments(
            raw, valid_codes, [str(q['question_id']) for q in batch]))
    return result


def attach_outcomes(questions: List[Dict[str, Any]],
                    assignments: Dict[str, List[str]]) -> None:
    """Ghi list mã CĐR vào từng record (in-place).

    Câu không có kết quả phân loại (LLM lỗi/parse fail/judge trả rỗng) giữ
    nhãn sơ bộ đã gán từ slot lúc sinh (nếu có); ngược lại -> [].
    """
    for q in questions:
        qid = str(q.get('question_id') or '')
        q['learning_outcomes'] = (assignments.get(qid)
                                  or q.get('learning_outcomes') or [])
