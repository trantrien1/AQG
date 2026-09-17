"""DirectPdfQuestionGenerator: điều phối sinh MCQ trực tiếp từ PDF (Req 2, 3, 6.3).

Đọc bytes PDF -> build_pdf_user_content -> call_llm_with_pdf -> parse JSON theo
Question_Schema hiện có (tái dùng generator._parse_json_response + schema.to_question_record).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import config as cfg
from .. import generator as gen
from .. import schema
from .. import verifier as verifier_mod
from ..agents.verifier_agent import recover_numeric_eval_against_key
from ..llm_client import call_llm_with_pdf
from .attach import (
    PdfAttachError,
    build_pdf_image_content,
    build_pdf_user_content,
)

ProgressCallback = Callable[[Dict[str, Any]], None]


def _synthetic_slot(index: int, item: Dict[str, Any]) -> Dict[str, Any]:
    """Dựng slot tối thiểu để to_question_record hoạt động cho Direct_PDF_Mode."""
    cognitive = ''
    difficulty_target = 0.5
    if isinstance(item, dict):
        cognitive = str(
            item.get('cognitive_level')
            or item.get('bloom_level')
            or ''
        ).strip()
        try:
            difficulty_target = float(item.get('difficulty_target', difficulty_target))
        except (TypeError, ValueError):
            difficulty_target = 0.5
    if not cognitive:
        cognitive = 'Thông hiểu'
    return {
        'slot_id': f'direct_pdf_{index}',
        'cognitive_level': cognitive,
        'difficulty_target': difficulty_target,
        'topic': '',
        'question_pattern': 'conceptual',
        'skill': '',
        'expected_question_type': 'single_choice',
        'doc_id': None,
    }


def _salvage_items(text: str) -> List[Any]:
    """Trích các object JSON hoàn chỉnh bên trong mảng đầu tiên của `text`.

    Dùng khi phản hồi mô hình bị cắt cụt (max_tokens) khiến JSON tổng không parse
    được: vẫn khôi phục được các câu HOÀN CHỈNH trước điểm cắt, bỏ item dở dang.
    Quét có nhận biết chuỗi/escape để không nhầm dấu ngoặc { } trong LaTeX.
    """
    if not isinstance(text, str):
        return []
    start = text.find('[')
    if start < 0:
        return []
    items: List[Any] = []
    depth = 0
    obj_start: Optional[int] = None
    in_str = False
    esc = False
    for i in range(start + 1, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif c == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and obj_start is not None:
                    frag = text[obj_start:i + 1]
                    try:
                        items.append(json.loads(frag))
                    except Exception:
                        try:
                            items.append(gen.loads_json_maybe_repair(frag))
                        except Exception:
                            pass
                    obj_start = None
    return items


def _iter_items(raw_or_items: Any) -> List[Any]:
    """Chuẩn hoá input về danh sách item MCQ.

    Chấp nhận: dict có key 'questions' (hoặc items/mcqs/data), một chuỗi JSON,
    hoặc một list. Không raise. Nếu JSON tổng không parse được (thường do bị cắt
    cụt), thử salvage các object hoàn chỉnh trong mảng.
    """
    obj: Any = raw_or_items

    if isinstance(obj, str):
        parsed = gen._first_json_object(obj)
        if parsed is not None:
            obj = parsed
        else:
            return _salvage_items(raw_or_items)

    if isinstance(obj, dict):
        for key in ('questions', 'items', 'mcqs', 'data', 'outputs'):
            if isinstance(obj.get(key), list):
                lst = list(obj[key])
                if not lst and isinstance(raw_or_items, str):
                    salvaged = _salvage_items(raw_or_items)
                    if salvaged:
                        return salvaged
                return lst
        # dict đơn lẻ = một item
        return [obj]

    if isinstance(obj, list):
        return list(obj)

    return []


def _coerce_number(value: Any) -> Optional[float]:
    """Trích một số float từ giá trị mô hình trả (số, chuỗi có LaTeX/đơn vị/phân số).

    Xử lý được: 68, "68 mét", "\\(68\\)", "3/2", "\\frac{3}{2}", "1,310" (dấu phân
    cách nghìn). Trả None nếu không tìm được số nào — để verify bỏ qua thay vì crash.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Bỏ wrapper LaTeX inline và ký hiệu tiền tệ/đơn vị hiển thị.
    s = s.replace('\\(', ' ').replace('\\)', ' ').replace('$', ' ')
    s = s.replace('\\,', '').replace('\\!', '').replace('\\;', '')
    # \frac{a}{b}
    mfrac = re.search(r'\\d?frac\{(-?\d+(?:\.\d+)?)\}\{(-?\d+(?:\.\d+)?)\}', s)
    if mfrac:
        num, den = float(mfrac.group(1)), float(mfrac.group(2))
        if den != 0:
            return num / den
    # Bỏ dấu phân cách nghìn kiểu 1,310 -> 1310.
    s = re.sub(r'(?<=\d),(?=\d{3}\b)', '', s)
    # Phân số a/b (ưu tiên trước số đơn để không nuốt mẫu số).
    mslash = re.search(r'(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)', s)
    if mslash:
        num, den = float(mslash.group(1)), float(mslash.group(2))
        if den != 0:
            return num / den
    mnum = re.search(r'-?\d+(?:\.\d+)?', s)
    if mnum:
        try:
            return float(mnum.group(0))
        except ValueError:
            return None
    return None


def _sanitize_expr(expr: Any) -> Optional[str]:
    """Làm sạch biểu thức số học cho SymPy: bỏ LaTeX, ^->**, ký hiệu Unicode."""
    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return repr(expr)
    if not isinstance(expr, str):
        return None
    e = expr.strip()
    if not e:
        return None
    e = e.replace('\\(', ' ').replace('\\)', ' ').replace('$', ' ')
    e = e.replace('\\cdot', '*').replace('\\times', '*').replace('\\div', '/')
    e = re.sub(r'\\[a-zA-Z]+', ' ', e)          # bỏ các lệnh LaTeX còn lại
    e = e.replace('{', '(').replace('}', ')')
    e = e.replace('^', '**')
    e = (e.replace('×', '*').replace('÷', '/').replace('−', '-')
          .replace('·', '*').replace(',', ''))
    e = e.strip()
    return e or None


def _numeric_tolerance(expected: float) -> float:
    """Dung sai so sánh: tương đối theo độ lớn nhưng đủ chặt để bắt sai số thật.

    Ví dụ 99.333 vs 99.33 (làm tròn) vẫn khớp, nhưng 64 vs 68 (sai đáp án) bị loại.
    """
    return max(1e-3, abs(expected) * 5e-3)


def _normalize_verifier_hint(hint: Any, answer_text: str = '') -> Dict[str, Any]:
    """Chuẩn hoá verifier_hint của mô hình về đúng key mà pipeline.verifier cần.

    Mô hình hay dùng alias (expression/expected/expected_value...) khác với schema
    verifier (expr/expected_numeric), hoặc nhét đơn vị/LaTeX vào số, hoặc bỏ hẳn
    expected_numeric. Trước đây các trường hợp này làm verifier ném lỗi và câu bị
    GIỮ mà không kiểm (bỏ sót đáp án sai). Ở đây ta:
      - gom nhiều alias cho expr và expected_numeric,
      - ép số qua _coerce_number (bỏ đơn vị/LaTeX/phân số),
      - nếu vẫn thiếu expected_numeric thì suy từ answer_text (chính là số đáp án
        đúng) để đối chiếu với expr — bắt được câu chọn sai phương án,
      - nếu vẫn không đủ (expr/expected) thì hạ type=none để verify bỏ qua sạch sẽ
        thay vì ném KeyError.
    """
    if not isinstance(hint, dict):
        return {'type': 'none', 'payload': {}}
    t = str(hint.get('type') or 'none').strip()
    payload = hint.get('payload')
    if not isinstance(payload, dict):
        payload = {}
    p = dict(payload)

    if t == 'numeric_eval':
        expr_raw = p.get('expr')
        if expr_raw is None:
            for alias in ('expression', 'formula', 'value_expr', 'calc', 'computation'):
                if p.get(alias) is not None:
                    expr_raw = p[alias]
                    break
        expr = _sanitize_expr(expr_raw)

        expected = None
        for key in ('expected_numeric', 'expected', 'expected_value', 'value',
                    'result', 'answer', 'numeric', 'val', 'expected_result',
                    'answer_numeric'):
            if p.get(key) is not None:
                expected = _coerce_number(p[key])
                if expected is not None:
                    break
        if expected is None and answer_text:
            expected = _coerce_number(answer_text)

        if expr is None or expected is None:
            # Không đủ dữ kiện để kiểm số học -> để verify bỏ qua, không ném lỗi.
            return {'type': 'none', 'payload': {}}
        p = {
            'expr': expr,
            'expected_numeric': expected,
            'tolerance': _numeric_tolerance(expected),
        }
    elif t == 'counting':
        expected = None
        for key in ('expected', 'expected_value', 'value', 'result'):
            if p.get(key) is not None:
                expected = _coerce_number(p[key])
                if expected is not None:
                    break
        if expected is not None:
            p['expected'] = int(expected) if float(expected).is_integer() else expected
    return {'type': t, 'payload': p}


def _norm_option_text(text: Any) -> str:
    """Chuẩn hoá text phương án để so trùng (bỏ khoảng trắng thừa + thường hoá)."""
    return re.sub(r'\s+', ' ', str(text or '').strip().lower())


def _structural_ok(candidate: Dict[str, Any]) -> bool:
    """Kiểm tra cấu trúc rẻ: có đáp án, đúng 3 distractor, 4 phương án phân biệt.

    Bắt lỗi: đáp án trùng một distractor, hoặc hai distractor trùng nhau (khiến MCQ
    có nhiều "đáp án" giống hệt hoặc distractor vô nghĩa).
    """
    answer = _norm_option_text(candidate.get('answer_text'))
    if not answer:
        return False
    distractors = candidate.get('distractors') or []
    if len(distractors) != 3:
        return False
    texts = [answer]
    for d in distractors:
        dt = _norm_option_text(d.get('distractor_text'))
        if not dt:
            return False
        texts.append(dt)
    return len(set(texts)) == 4


def parse_direct_pdf_response(
    raw_or_items: Any,
    verify_numeric: Optional[bool] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Tách + xác thực danh sách MCQ từ JSON của mô hình.

    Với mỗi item: dùng lại generator._parse_json_response + generator.is_valid;
    item hợp lệ được convert qua slot tổng hợp + schema.to_question_record. Item
    không hợp lệ (schema) bị loại và tăng parse_errors.

    Nếu `verify_numeric` bật (mặc định theo cfg.DIRECT_PDF_VERIFY): chạy
    pipeline.verifier trên verifier_hint; kết quả (kể cả verified=False) chỉ
    ghi vào `_verification` và đếm verify_failures, KHÔNG loại câu — mismatch
    thường do hint viết lệch chứ không phải LLM tính sai.

    Không bao giờ raise. Trả về (questions, parse_errors, verify_failures).
    """
    if verify_numeric is None:
        verify_numeric = bool(getattr(cfg, 'DIRECT_PDF_VERIFY', True))
    items = _iter_items(raw_or_items)
    questions: List[Dict[str, Any]] = []
    parse_errors = 0
    verify_failures = 0

    for i, item in enumerate(items):
        try:
            candidate = gen._parse_json_response(json.dumps(item, ensure_ascii=False))
            if not candidate or not gen.is_valid(candidate):
                parse_errors += 1
                continue

            # Cổng cấu trúc: đúng 1 đáp án + 3 distractor phân biệt (bắt câu có
            # đáp án đúng trùng distractor hoặc distractor trùng nhau).
            if not _structural_ok(candidate):
                parse_errors += 1
                continue

            verification: Dict[str, Any] = {}
            if verify_numeric:
                hint = _normalize_verifier_hint(
                    candidate.get('verifier_hint'),
                    answer_text=candidate.get('answer_text', ''),
                )
                if hint.get('type') not in (None, '', 'none'):
                    try:
                        vres = verifier_mod.verify(hint)
                    except Exception:
                        vres = None
                    if vres is not None:
                        # numeric_eval false-flag recovery (đồng bộ với
                        # VerifierAgent): expr khớp đáp án key thì nâng lên
                        # verified=True dù expected_numeric writer viết lệch.
                        recover_numeric_eval_against_key(
                            vres, candidate.get('answer_text', ''))
                        # verified=False KHÔNG loại (đồng bộ với VerifierAgent):
                        # mismatch thường do verifier_hint viết lệch, không phải
                        # LLM tính sai. Chỉ đếm verify_failures để theo dõi.
                        if vres.verified is False:
                            verify_failures += 1
                        verification = {
                            'engine': vres.engine,
                            'verified': vres.verified,
                            'detail': vres.detail,
                            'numeric_crosscheck_points': getattr(
                                vres, 'numeric_crosscheck_points', 0),
                        }

            candidate['_verification'] = verification
            slot = _synthetic_slot(i, item if isinstance(item, dict) else {})
            record = schema.to_question_record(slot, candidate)
            questions.append(record)
        except Exception:
            parse_errors += 1
            continue

    return questions, parse_errors, verify_failures


@dataclass
class DirectPdfResult:
    questions: List[Dict[str, Any]] = field(default_factory=list)
    accepted_count: int = 0
    requested_count: int = 0
    is_partial: bool = False
    parse_errors: int = 0
    verify_failures: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    # Câu bị loại kèm lý do (stem/options nếu dựng được) — web lưu vào
    # debug_rejected.json cho tab "Từ chối"; monolith cũ không điền field này.
    rejected: List[Dict[str, Any]] = field(default_factory=list)


def _bloom_lines(bloom_distribution: Optional[List[Dict[str, Any]]]) -> str:
    if not bloom_distribution:
        return '- Phân bố Bloom: hỗn hợp hợp lý (mặc định), ưu tiên hiểu và vận dụng.'
    lines = []
    for b in bloom_distribution:
        level = b.get('cognitive_level') or b.get('level') or ''
        ratio = b.get('fraction')
        if ratio is None:
            ratio = b.get('ratio')
        if ratio is not None:
            lines.append(f'- {level}: tỉ lệ ~{ratio}')
        else:
            lines.append(f'- {level}')
    return 'Phân bố mức Bloom yêu cầu:\n' + '\n'.join(lines)


def _avoid_block(avoid_stems: Optional[List[str]]) -> str:
    if not avoid_stems:
        return ''
    lines = []
    for s in avoid_stems[:40]:
        s = re.sub(r'\s+', ' ', str(s or '')).strip()
        if s:
            lines.append(f'- {s[:160]}')
    if not lines:
        return ''
    return (
        '\n\nĐÃ CÓ các câu hỏi sau (KHÔNG lặp lại, KHÔNG hỏi cùng dạng/số liệu; '
        'hãy khai thác nội dung/kỹ năng KHÁC trong tài liệu):\n' + '\n'.join(lines) + '\n'
    )


def _feedback_block(feedback_guidance: Optional[str]) -> str:
    g = str(feedback_guidance or '').strip()
    if not g:
        return ''
    return (
        '\n\nPHẢN HỒI NGƯỜI DÙNG từ lượt sinh trước (BẮT BUỘC ưu tiên tuân thủ '
        'khi soạn câu mới):\n' + g + '\n'
    )


def _outcomes_block(learning_outcomes: Optional[List[Dict[str, str]]]) -> str:
    """Khối Chuẩn đầu ra cho prompt monolith: phủ đều các CĐR trên toàn lô."""
    items = [o for o in (learning_outcomes or [])
             if isinstance(o, dict) and str(o.get('description') or '').strip()]
    if not items:
        return ''
    lines = [f"- {str(o.get('code') or f'CĐR{i + 1}').strip()}: "
             f"{str(o['description']).strip()[:500]}"
             for i, o in enumerate(items)]
    return (
        '\n\nCHUẨN ĐẦU RA (bắt buộc): mỗi câu hỏi phải kiểm tra TRỰC TIẾP một trong '
        'các chuẩn đầu ra sau, và cả bộ câu hỏi phải PHỦ ĐỀU các chuẩn (số câu chia '
        'đều cho từng chuẩn, chênh lệch tối đa 1 câu):\n' + '\n'.join(lines) + '\n'
    )


def _build_prompt(requested_count: int,
                  bloom_distribution: Optional[List[Dict[str, Any]]],
                  avoid_stems: Optional[List[str]] = None,
                  feedback_guidance: str = '',
                  learning_outcomes: Optional[List[Dict[str, str]]] = None) -> str:
    return (
        'Bạn được đính kèm nội dung một tài liệu Toán trong message này (các trang '
        'tài liệu, có thể ở dạng ảnh từng trang hoặc file PDF). '
        'Hãy ĐỌC TRỰC TIẾP toàn bộ nội dung tài liệu (bao gồm công thức, bảng, hình nếu có) '
        f'và sinh CHÍNH XÁC {requested_count} câu hỏi trắc nghiệm (MCQ) bám sát nội dung tài liệu.\n\n'
        f'Số câu hỏi cần sinh: {requested_count}\n'
        f'{_bloom_lines(bloom_distribution)}'
        f'{_outcomes_block(learning_outcomes)}'
        f'{_feedback_block(feedback_guidance)}'
        f'{_avoid_block(avoid_stems)}\n\n'
        'Mỗi câu hỏi phải tuân thủ Question_Schema dưới đây và trả về DUY NHẤT một JSON '
        'object hợp lệ dạng {"questions": [ <mỗi phần tử theo schema bên dưới> ]}. '
        'Không kèm markdown/code fence, không thêm chữ ngoài JSON.\n\n'
        'Schema cho MỖI phần tử trong "questions" (áp dụng đúng như mô tả):\n'
        f'{gen._FULL_MCQ_JSON_FORMAT}\n\n'
        f'LƯU Ý: mảng "questions" phải có đúng {requested_count} phần tử, mỗi phần tử là '
        'một MCQ đầy đủ theo schema trên (question, options 4 phương án, answer_key, '
        'explanation, detailed_solution, source_quote trích từ PDF...).\n\n'
        'RẤT QUAN TRỌNG — ĐỌC KỸ: Tài liệu có thể gồm nhiều BÀI TẬP MẪU/VÍ DỤ ĐÃ GIẢI. '
        'Bạn ĐƯỢC PHÉP và ĐƯỢC KHUYẾN KHÍCH tạo câu hỏi MỚI dựa trên cùng PHƯƠNG PHÁP, '
        'KHÁI NIỆM, DẠNG BÀI trong tài liệu nhưng THAY số liệu/tình huống/tên gọi khác đi '
        '(không chép nguyên văn bài tập cũ). Việc tạo bài tương tự với số liệu mới là YÊU '
        'CẦU HỢP LỆ và mang tính giáo dục — TUYỆT ĐỐI KHÔNG từ chối vì lý do "chỉ là định '
        'dạng lại bài có sẵn" hay "vi phạm quy tắc không diễn giải". Trong MỌI trường hợp '
        'phải trả về JSON đúng schema; KHÔNG được trả lời bằng văn xuôi từ chối.'
    )


def _build_review_prompt(requested_count: int, draft_json_str: str) -> str:
    """Prompt lượt 2: cho model tự rà soát & sửa danh sách câu hỏi nháp."""
    return (
        'Dưới đây là DANH SÁCH CÂU HỎI NHÁP (JSON) mà bạn vừa sinh từ tài liệu đính '
        'kèm ở trên. Hãy RÀ SOÁT KỸ và SỬA từng câu để đảm bảo mọi tiêu chí sau:\n'
        '1. Số học/biến đổi CHÍNH XÁC. Tự giải lại từng câu; đáp án đúng phải khớp với '
        'kết quả trong detailed_solution.final_answer.\n'
        '2. Giá trị đáp án đúng PHẢI là một trong 4 options. Nếu kết quả tính ra không '
        'nằm trong options, hãy SỬA options (hoặc chỉnh số liệu đề cho tròn/hợp lý) sao '
        'cho đáp án đúng thực sự nằm trong 4 lựa chọn và answer_key trỏ đúng.\n'
        '3. Chỉ có ĐÚNG MỘT đáp án đúng; 3 distractor còn lại phải SAI nhưng hợp lý '
        '(gắn với lỗi thường gặp), không trùng đáp án đúng.\n'
        '4. source_quote phải trích NGUYÊN VĂN từ tài liệu và LIÊN QUAN trực tiếp tới đề '
        'của CHÍNH câu đó. Nếu quote không khớp đề, thay bằng đoạn đúng trong tài liệu; '
        'nếu không có, để chuỗi rỗng "".\n'
        '5. TUYỆT ĐỐI không để lời giải chứa câu kiểu "có thể đề sai", "làm tròn gần '
        'đúng", "cần kiểm tra" — phải sửa cho dứt điểm, nhất quán.\n'
        '6. Giữ nguyên SỐ CÂU và đúng schema JSON như bản nháp.\n\n'
        'Câu nào đã đúng thì giữ nguyên. Chỉ trả về DUY NHẤT một JSON hợp lệ dạng '
        '{"questions": [ ... ]} đã sửa, KHÔNG kèm markdown/giải thích ngoài JSON.\n\n'
        f'CÂU HỎI NHÁP CẦN RÀ SOÁT:\n{draft_json_str}'
    )


class DirectPdfQuestionGenerator:
    def __init__(self, model: Optional[str] = None):
        self.model = model or cfg.GENERATOR_MODEL

    def _self_review(self, attachment_parts: List[Dict[str, Any]], draft_raw: str,
                     model: str, max_tokens: int) -> str:
        """Lượt 2: gửi lại tài liệu + câu nháp, yêu cầu model sửa. Trả raw đã sửa.

        Fail-safe: nếu lượt review lỗi hoặc trả JSON rỗng/không parse được, giữ
        nguyên bản nháp (không làm hỏng kết quả lượt 1).
        """
        draft_obj = gen._first_json_object(draft_raw)
        if not draft_obj or not isinstance(draft_obj.get('questions'), list) \
                or not draft_obj['questions']:
            return draft_raw
        draft_json_str = json.dumps(
            {'questions': draft_obj['questions']}, ensure_ascii=False
        )
        review_content = (
            [{'type': 'text', 'text': _build_review_prompt(
                len(draft_obj['questions']), draft_json_str)}]
            + attachment_parts
        )
        try:
            reviewed = call_llm_with_pdf(
                system=cfg.SYSTEM_PROMPT,
                user_content=review_content,
                model=model,
                max_tokens=max_tokens,
            )
        except Exception:
            return draft_raw
        reviewed_obj = gen._first_json_object(reviewed)
        if reviewed_obj and isinstance(reviewed_obj.get('questions'), list) \
                and reviewed_obj['questions']:
            return reviewed
        return draft_raw

    def generate(
        self,
        pdf_path: str,
        requested_count: int,
        bloom_distribution: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        feedback_guidance: str = '',
        seed_avoid_stems: Optional[List[str]] = None,
        include_explanation: bool = True,
        attachment_parts: Optional[List[Dict[str, Any]]] = None,
        learning_outcomes: Optional[List[Dict[str, str]]] = None,
    ) -> DirectPdfResult:
        # Multi-agent branch (Writer -> Distractor -> Verifier -> Critic ->
        # Formatter). Bật mặc định; tắt bằng AQG_DIRECT_PDF_MULTI_AGENT=0 để
        # dùng lại monolith cũ bên dưới. Cùng contract DirectPdfResult nên
        # runner/web tiêu thụ không đổi.
        if getattr(cfg, 'DIRECT_PDF_MULTI_AGENT', True):
            from .agents.pdf_orchestrator import DirectPdfOrchestrator
            return DirectPdfOrchestrator(model=model or self.model).generate(
                pdf_path=pdf_path,
                requested_count=requested_count,
                bloom_distribution=bloom_distribution,
                model=model or self.model,
                progress_callback=progress_callback,
                feedback_guidance=feedback_guidance,
                seed_avoid_stems=seed_avoid_stems,
                include_explanation=include_explanation,
                attachment_parts=attachment_parts,
                learning_outcomes=learning_outcomes,
            )

        # 1. Đọc bytes PDF + build phần đính kèm (Req 2.1) — dựng MỘT LẦN, tái
        # dùng cho mọi lô để không phải render lại ảnh.
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        filename = os.path.basename(pdf_path)
        seed_prompt = _build_prompt(requested_count, bloom_distribution,
                                    learning_outcomes=learning_outcomes)
        def _emit(**event: Any) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(event)
            except Exception:
                pass

        _emit(stage='preparing_pdf', accepted=0, attempted=0, target=requested_count)
        if not attachment_parts:
            try:
                attach_mode = str(getattr(cfg, 'PDF_ATTACH_MODE', 'image')).lower()
                # Chỉ bật tiền tố cache cho OpenRouter: đường chat2api đang
                # chạy tốt với thứ tự cũ và đã sinh ra ngữ liệu hiện có,
                # không đổi hành vi của nó vì một tối ưu chi phí.
                _cacheable = (cfg.LLM_PROVIDER == 'openrouter'
                              and attach_mode != 'file_url')
                if attach_mode == 'image':
                    base_content = build_pdf_image_content(
                        pdf_bytes,
                        filename,
                        seed_prompt,
                        dpi=getattr(cfg, 'PDF_IMAGE_DPI', 120),
                        max_pages=getattr(cfg, 'PDF_IMAGE_MAX_PAGES', 30),
                        images_first=_cacheable,
                        cache_control=_cacheable,
                    )
                else:
                    base_content = build_pdf_user_content(
                        pdf_bytes, filename, seed_prompt,
                        as_image_url=(attach_mode == 'file_url'),
                        pdf_first=_cacheable,
                        cache_control=_cacheable,
                    )
            except PdfAttachError as e:
                return DirectPdfResult(
                    questions=[],
                    accepted_count=0,
                    requested_count=requested_count,
                    is_partial=requested_count > 0,
                    parse_errors=0,
                    error_code='attach_failed',
                    error_message=str(e),
                )
            attachment_parts = [p for p in base_content if p.get('type') != 'text']
        _emit(stage='pdf_ready', accepted=0, attempted=0, target=requested_count)
        active_model = model or self.model
        per_q = int(getattr(cfg, 'DIRECT_PDF_TOKENS_PER_QUESTION', 1200))
        batch_size = max(1, int(getattr(cfg, 'DIRECT_PDF_BATCH_SIZE', 6)))

        # 2. Sinh (một lô hoặc nhiều lô). Lô nhỏ tránh model từ chối/cắt cụt khi
        # phải sinh quá nhiều câu mới cùng lúc.
        questions: List[Dict[str, Any]] = []
        parse_errors = 0
        verify_failures = 0
        seen: set = set()

        seed_avoid = [str(s) for s in (seed_avoid_stems or []) if str(s or '').strip()]

        def _run_batch(n: int) -> Tuple[List[Dict[str, Any]], int, int]:
            prompt = _build_prompt(
                n, bloom_distribution,
                avoid_stems=seed_avoid + [q.get('stem', '') for q in questions],
                feedback_guidance=feedback_guidance,
                learning_outcomes=learning_outcomes,
            )
            content = [{'type': 'text', 'text': prompt}] + attachment_parts
            mt = max(int(cfg.GEN_MAX_TOKENS), per_q * max(1, n) + 800)
            raw = call_llm_with_pdf(
                system=cfg.SYSTEM_PROMPT,
                user_content=content,
                model=active_model,
                max_tokens=mt,
            )
            if getattr(cfg, 'DIRECT_PDF_SELF_REVIEW', True):
                rounds = max(1, int(getattr(cfg, 'DIRECT_PDF_REVIEW_ROUNDS', 1)))
                for _ in range(rounds):
                    raw = self._self_review(attachment_parts, raw, active_model, mt)
            return parse_direct_pdf_response(raw)

        def _add(batch_qs: List[Dict[str, Any]]) -> None:
            for q in batch_qs:
                key = re.sub(r'\s+', ' ', str(q.get('stem', '')).strip().lower())[:80]
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                questions.append(q)

        # Luôn dùng vòng lặp lô để tự bù khi verify/dedup loại bớt câu, và chịu
        # được vài lần model từ chối tạm thời (nondeterministic). Dừng khi đủ số
        # câu hoặc gặp nhiều lô rỗng LIÊN TIẾP (tránh loop vô ích).
        import math
        max_batches = math.ceil(requested_count / batch_size) + 4
        empty_streak = 0
        max_empty_streak = 3
        for batch_index in range(max_batches):
            if len(questions) >= requested_count:
                break
            need = min(batch_size, requested_count - len(questions))
            _emit(
                stage='batch_started',
                attempted=batch_index + 1,
                max_attempts=max_batches,
                accepted=len(questions),
                target=requested_count,
            )
            try:
                batch_qs, pe, vf = _run_batch(need)
            except Exception:
                empty_streak += 1
                _emit(
                    stage='batch_error',
                    attempted=batch_index + 1,
                    max_attempts=max_batches,
                    accepted=len(questions),
                    target=requested_count,
                    empty_streak=empty_streak,
                )
                if empty_streak >= max_empty_streak:
                    break
                continue
            parse_errors += pe
            verify_failures += vf
            before = len(questions)
            _add(batch_qs)
            if len(questions) == before:
                empty_streak += 1
                _emit(
                    stage='batch_rejected',
                    attempted=batch_index + 1,
                    max_attempts=max_batches,
                    accepted=len(questions),
                    target=requested_count,
                    parse_errors=parse_errors,
                    verify_failures=verify_failures,
                    empty_streak=empty_streak,
                )
                if empty_streak >= max_empty_streak:
                    break
            else:
                empty_streak = 0
                _emit(
                    stage='question_accepted',
                    attempted=batch_index + 1,
                    max_attempts=max_batches,
                    accepted=len(questions),
                    target=requested_count,
                    parse_errors=parse_errors,
                    verify_failures=verify_failures,
                )

        questions = questions[:requested_count]

        # 3. Đánh giá đủ / partial (Req 3.4, 3.5).
        accepted_count = len(questions)
        _emit(
            stage='generation_finished',
            attempted=max_batches,
            max_attempts=max_batches,
            accepted=accepted_count,
            target=requested_count,
            parse_errors=parse_errors,
            verify_failures=verify_failures,
        )
        return DirectPdfResult(
            questions=questions,
            accepted_count=accepted_count,
            requested_count=requested_count,
            is_partial=accepted_count < requested_count,
            parse_errors=parse_errors,
            verify_failures=verify_failures,
            error_code=None,
            error_message=None,
        )
